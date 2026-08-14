"""
geofa_routes.py

Fetch Danish route/trail line geometries (Cykelrute, Vandrerute,
Kanoerute, ...) from GeoFA's public SQL API.

Unlike the OSM-based cycle *nodes* module (geofa_cycle_nodes.py),
route/trail geometries come from GeoFA's own SQL API, querying table
fkg.t_5802_fac_li ("facility lines"). No API key is required for
read queries.

Docs: https://www.geodanmark.dk/home/vejledninger/geofa/vejledninger-til-geofa/

Example
-------
    from geofa_routes import RouteClient

    client = RouteClient()
    routes = client.get_routes(route_type="Cykelrute", bbox=(55.4, 12.0, 56.0, 12.8))
    geojson = client.to_geojson(routes)

CLI
---
    python3 geofa_routes.py --type Cykelrute --bbox 55.4,12.0,56.0,12.8 --out routes.geojson
    python3 geofa_routes.py --type Vandrerute --min-length-m 5000 --limit 50
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Optional

GEOFA_SQL_ENDPOINT = "https://geofa.geodanmark.dk/api/v2/sql/fkg"

FACILITY_LINE_TABLE = "fkg.t_5802_fac_li"

# Known rute_ty (route type) values in fkg.t_5802_fac_li.
ROUTE_TYPE_CYKELRUTE = "Cykelrute"
ROUTE_TYPE_VANDRERUTE = "Vandrerute"
ROUTE_TYPE_KANORUTE = "Kanoerute"


class GeoFAError(RuntimeError):
    """Raised when the GeoFA SQL API request fails or returns an error."""


@dataclass
class Route:
    """A single facility line (route/trail) from fkg.t_5802_fac_li."""

    name: Optional[str]
    route_type: Optional[str]
    length_m: Optional[float]
    geometry: dict
    extra: dict = field(default_factory=dict)

    def to_geojson_feature(self) -> dict:
        return {
            "type": "Feature",
            "geometry": self.geometry,
            "properties": {
                "navn": self.name,
                "rute_ty": self.route_type,
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
        route_type: Optional[str] = None,
        min_length_m: Optional[float] = None,
        max_length_m: Optional[float] = None,
        bbox: Optional[tuple[float, float, float, float]] = None,
        columns: str = "navn,rute_ty,ST_Length(geometri) AS length_m,geometri",
        limit: int = 200,
        srs: int = 4326,
    ) -> list[Route]:
        """Fetch routes/trails, optionally filtered by type, length, or a WGS84 bbox.

        Args:
            route_type:   e.g. "Cykelrute", "Vandrerute", "Kanoerute" (exact match).
            min_length_m: only routes longer than this many metres.
            max_length_m: only routes shorter than this many metres.
            bbox:         (south, west, north, east) in WGS84 — filters to routes
                          intersecting this envelope.
            columns:      SQL select list. Must include `geometri` for geometry output.
            limit:        max rows to return.
            srs:          EPSG code for the returned geometry (default 4326/WGS84).
        """
        clauses = []
        if route_type:
            clauses.append(f"rute_ty = '{self._escape(route_type)}'")
        if min_length_m is not None:
            clauses.append(f"ST_Length(geometri) > {float(min_length_m)}")
        if max_length_m is not None:
            clauses.append(f"ST_Length(geometri) < {float(max_length_m)}")
        if bbox is not None:
            south, west, north, east = bbox
            clauses.append(
                f"ST_Intersects(geometri, ST_MakeEnvelope({west}, {south}, {east}, {north}, 4326))"
            )

        sql = f"SELECT {columns} FROM {FACILITY_LINE_TABLE}"
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
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                if not payload.get("data", {}).get("success", True) and "data" in payload:
                    raise GeoFAError(f"GeoFA API reported failure: {payload}")
                return payload
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_err = exc
                time.sleep(1.5 * (attempt + 1))

        raise GeoFAError(f"Failed to fetch from GeoFA SQL API: {last_err}")

    @staticmethod
    def _parse(payload: dict) -> list[Route]:
        features = payload.get("data", {}).get("features", [])
        routes = []
        for feat in features:
            props = dict(feat.get("properties", {}) or {})
            name = props.pop("navn", None)
            route_type = props.pop("rute_ty", None)
            length_m = props.pop("length_m", None)
            routes.append(
                Route(
                    name=name,
                    route_type=route_type,
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
        description="Fetch Danish route/trail geometries (Cykelrute/Vandrerute/Kanoerute) from GeoFA."
    )
    parser.add_argument("--type", dest="route_type", help='e.g. "Cykelrute", "Vandrerute", "Kanoerute"')
    parser.add_argument("--bbox", help="south,west,north,east (WGS84)")
    parser.add_argument("--min-length-m", type=float, default=None)
    parser.add_argument("--max-length-m", type=float, default=None)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--out", default="-", help="Output file path, or - for stdout")
    parser.add_argument("--format", choices=["geojson", "json"], default="geojson")
    args = parser.parse_args()

    client = RouteClient()
    bbox = tuple(float(x) for x in args.bbox.split(",")) if args.bbox else None

    routes = client.get_routes(
        route_type=args.route_type,
        min_length_m=args.min_length_m,
        max_length_m=args.max_length_m,
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
