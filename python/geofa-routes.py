"""
geofa_routes.py

Fetch Danish bike-node-network segment geometries (Cykelknudepunktsstraekninger,
GeoFA theme 5609) from GeoFA's public SQL API.

This is the segment/line counterpart to the cykelknudepunkter *nodes* theme
(5608) — table fkg.t_5609_cykelkrydspunktsstraekninger. Note the "kryds"
spelling in the live table name (not "knude", despite the theme's Danish
name and every field in the spec PDF using "knude"). This theme has no
`navn`/`rute_ty` columns — it is not typed by route (Cykelrute/Vandrerute/
Kanoerute); segments are described by `beliggenhedskommune` (kommune code)
and boolean surface/access flags (`asfalteret`, `privatvej`). No API key is
required for read queries.

Docs: https://www.geodanmark.dk/home/vejledninger/geofa/vejledninger-til-geofa/

Example
-------
    from geofa_routes import RouteClient

    client = RouteClient()
    routes = client.get_routes(beliggenhedskommune=570, bbox=(55.4, 12.0, 56.0, 12.8))
    geojson = client.to_geojson(routes)

CLI
---
    python3 geofa-routes.py --bbox 55.4,12.0,56.0,12.8 --out routes.geojson
    python3 geofa-routes.py --beliggenhedskommune=570 --limit 50
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Optional

try:
    import certifi

    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = ssl.create_default_context()

GEOFA_SQL_ENDPOINT = "https://geofa.geodanmark.dk/api/v2/sql/fkg"

ROUTE_TABLE = "fkg.t_5609_cykelkrydspunktsstraekninger"

class GeoFAError(RuntimeError):
    """Raised when the GeoFA SQL API request fails or returns an error."""

@dataclass
class Route:
    """A single bike-node-network segment from fkg.t_5609_cykelkrydspunktsstraekninger."""

    beliggenhedskommune: Optional[int]
    privatvej: Optional[bool]
    asfalteret: Optional[bool]
    length_m: Optional[float]
    geometry: dict
    extra: dict = field(default_factory=dict)

    def to_geojson_feature(self) -> dict:
        return {
            "type": "Feature",
            "geometry": self.geometry,
            "properties": {
                "beliggenhedskommune": self.beliggenhedskommune,
                "privatvej": self.privatvej,
                "asfalteret": self.asfalteret,
                "length_m": self.length_m,
                **self.extra,
            },
        }

class RouteClient:
    """Client for fetching Danish route/trail geometries from the GeoFA SQL API."""

    def __init__(
        self,
        endpoint: str = GEOFA_SQL_ENDPOINT,
        timeout: int = 30,
        retries: int = 2,
        user_agent: str = "geofa-routes/1.0 (personal research use)",
    ):
        self.endpoint = endpoint
        self.timeout = timeout
        self.retries = retries
        self.user_agent = user_agent

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def get_routes(
        self,
        beliggenhedskommune: Optional[int] = None,
        privatvej: Optional[bool] = None,
        asfalteret: Optional[bool] = None,
        bbox: Optional[tuple[float, float, float, float]] = None,
        columns: str = "beliggenhedskommune,privatvej,asfalteret,ST_Length(geometri) AS length_m,geometri",
        limit: int = 200,
        srs: int = 4326,
    ) -> list[Route]:
        """Fetch routes, optionally filtered by attributes or a WGS84 bbox.

        Args:
            beliggenhedskommune:    kommunekode, e.g. 570.
            privatvej:              filter on whether the segment crosses private land/road.
            asfalteret:             filter on whether the segment has a paved surface.
            bbox:                   (south, west, north, east) in WGS84 — filters to routes
                                    intersecting this envelope.
            columns:                SQL select list. Must include `geometri` for geometry output.
            limit:                  max rows to return.
            srs:                    EPSG code for the returned geometry (default 4326/WGS84).
        """
        clauses = []
        if beliggenhedskommune is not None:
            clauses.append(f"beliggenhedskommune = {int(beliggenhedskommune)}")
        if privatvej is not None:
            clauses.append(f"privatvej = {bool(privatvej)}")
        if asfalteret is not None:
            clauses.append(f"asfalteret = {bool(asfalteret)}")
        if bbox is not None:
            south, west, north, east = bbox
            clauses.append(
                f"ST_Intersects(geometri, ST_MakeEnvelope({west}, {south}, {east}, {north}, 4326))"
            )

        sql = f"SELECT {columns} FROM {ROUTE_TABLE}"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += f" LIMIT {int(limit)}"

        data = self._fetch(sql, srs=srs)
        return self._parse(data)

    @staticmethod
    def to_geojson(routes: list[Route]) -> dict:
        return {"type": "FeatureCollection", "features": [r.to_geojson_feature() for r in routes]}

    @staticmethod
    def to_dicts(routes: list[Route]) -> list[dict]:
        return [asdict(r) for r in routes]

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    @staticmethod
    def _escape(value: str) -> str:
        """Escape single quotes for safe interpolation into the SQL string param."""
        return value.replace("'", "''")

    def _fetch(self, sql: str, srs: int, out_format: str = "geojson") -> dict:
        params = {"q": sql, "format": out_format, "srs": srs}
        url = f"{self.endpoint}?{urllib.parse.urlencode(params)}"
        last_err: Optional[Exception] = None

        for attempt in range(self.retries + 1):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
                with urllib.request.urlopen(req, timeout=self.timeout, context=_SSL_CONTEXT) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                # "success" and "features" are top-level keys on the API response,
                # not nested under a "data" key.
                if not payload.get("success", True):
                    raise GeoFAError(f"GeoFA API reported failure: {payload}")
                return payload
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_err = exc
                time.sleep(1.5 * (attempt + 1))

        raise GeoFAError(f"Failed to fetch from GeoFA SQL API: {last_err}")

    @staticmethod
    def _parse(payload: dict) -> list[Route]:
        features = payload.get("features", [])
        routes = []
        for feat in features:
            props = dict(feat.get("properties", {}) or {})
            beliggenhedskommune = props.pop("beliggenhedskommune", None)
            privatvej = props.pop("privatvej", None)
            asfalteret = props.pop("asfalteret", None)
            length_m = props.pop("length_m", None)
            routes.append(
                Route(
                    beliggenhedskommune=beliggenhedskommune,
                    privatvej=privatvej,
                    asfalteret=asfalteret,
                    length_m=length_m,
                    geometry=feat.get("geometry", {}),
                    extra=props,
                )
            )
        return routes


# ---------------------------------------------------------------------- #
# CLI
# ---------------------------------------------------------------------- #

def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Fetch Danish Recreational Bike Network Routes from GeoFA."
    )
    parser.add_argument("--beliggenhedskommune", dest="beliggenhedskommune", type=int, default=None, help="kommunekode, e.g. 570")
    parser.add_argument("--asfalteret", type=lambda v: v.lower() in ("1", "true", "yes"), default=None)
    parser.add_argument("--privatvej", type=lambda v: v.lower() in ("1", "true", "yes"), default=None)
    parser.add_argument("--bbox", help="south,west,north,east (WGS84)")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--out", default="-", help="Output file path, or - for stdout")
    parser.add_argument("--format", choices=["geojson", "json"], default="geojson")
    args = parser.parse_args()

    client = RouteClient()
    bbox = tuple(float(x) for x in args.bbox.split(",")) if args.bbox else None

    routes = client.get_routes(
        beliggenhedskommune=args.beliggenhedskommune,
        privatvej=args.privatvej,
        asfalteret=args.asfalteret,
        bbox=bbox,
        limit=args.limit,
    )

    result = client.to_geojson(routes) if args.format == "geojson" else client.to_dicts(routes)
    text = json.dumps(result, ensure_ascii=False, indent=2)

    if args.out == "-":
        print(text)
    else:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Wrote {len(routes)} routes to {args.out}")


if __name__ == "__main__":
    _cli()
