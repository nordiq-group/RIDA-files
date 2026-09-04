"""
geofa-nodes.py

Fetch Danish bike-node-network point geometries (Cykelkrydspunkter,
GeoFA theme 5608) from GeoFA's public SQL API.

This is the node/point counterpart to the cykelkrydspunktsstraekninger
*segments* theme (5609, see geofa-routes.py) — table
fkg.t_5608_cykelkrydspunkter. Note the "kryds" spelling in the live table
and column names (not "kryds", despite the theme's Danish name and every
field in the spec PDF using "kryds"). No API key is required for read
queries.

`krydspunktsnummer` (the signed node number cyclists see) is NOT globallyªß
unique — it repeats across kommuner and can even repeat within one kommune,
where an intersection is modeled as a primary node (`primaerpunkt=true`,
the one shown on the public map) plus one or more support nodes
(`primaerpunkt=false`). Filter to `primaerpunkt=true` for display/routing
use unless you specifically want the support points too.

Docs: https://www.geodanmark.dk/home/vejledninger/geofa/vejledninger-til-geofa/

Example
-------
    from geofa_nodes import NodeClient

    client = NodeClient()
    nodes = client.get_nodes(beliggenhedskommune=461, primaerpunkt=True)
    geojson = client.to_geojson(nodes)

CLI
---
    python3 geofa_nodes.py --bbox 55.4,12.0,56.0,12.8 --out nodes.geojson
    python3 geofa_nodes.py --beliggenhedskommune=461 --primaerpunkt true --limit 200
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

NODE_TABLE = "fkg.t_5608_cykelkrydspunkter"

class GeoFAError(RuntimeError):
    """Raised when the GeoFA SQL API request fails or returns an error."""

@dataclass
class Node:
    """A single bike-node-network point from fkg.t_5608_cykelkrydspunkter."""

    krydspunktsnummer: Optional[str]
    beliggenhedskommune: Optional[int]
    primaerpunkt: Optional[bool]
    blindt_punkt: Optional[bool]
    afm_krydspunkt: Optional[bool]
    geometry: dict
    extra: dict = field(default_factory=dict)

    def to_geojson_feature(self) -> dict:
        return {
            "type": "Feature",
            "geometry": self.geometry,
            "properties": {
                "krydspunktsnummer": self.krydspunktsnummer,
                "beliggenhedskommune": self.beliggenhedskommune,
                "primaerpunkt": self.primaerpunkt,
                "blindt_punkt": self.blindt_punkt,
                "afm_krydspunkt": self.afm_krydspunkt,
                **self.extra,
            },
        }

class NodeClient:
    """Client for fetching Danish bike-node-network points from the GeoFA SQL API."""

    def __init__(
        self,
        endpoint: str = GEOFA_SQL_ENDPOINT,
        timeout: int = 30,
        retries: int = 2,
        user_agent: str = "geofa-nodes/1.0 (personal research use)",
    ):
        self.endpoint = endpoint
        self.timeout = timeout
        self.retries = retries
        self.user_agent = user_agent

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def get_nodes(
        self,
        beliggenhedskommune: Optional[int] = None,
        krydspunktsnummer: Optional[str] = None,
        primaerpunkt: Optional[bool] = None,
        blindt_punkt: Optional[bool] = None,
        planstatus_kode: Optional[int] = None,
        bbox: Optional[tuple[float, float, float, float]] = None,
        columns: str = (
            "krydspunktsnummer,beliggenhedskommune,primaerpunkt,blindt_punkt,"
            "afm_krydspunkt,geometri"
        ),
        limit: int = 200,
        srs: int = 4326,
    ) -> list[Node]:
        """Fetch bike-node-network points, optionally filtered by attributes or a WGS84 bbox.

        Args:
            beliggenhedskommune: kommunekode, e.g. 461.
            krydspunktsnummer:   the signed node number (not globally unique — always
                                 scope by beliggenhedskommune too).
            primaerpunkt:        filter to the primary/display node (true) or support
                                 nodes only (false).
            blindt_punkt:        filter on whether the node is a dead end.
            planstatus_kode:     1 = Eksisterende (established), 2 = Planlagt (planned).
            bbox:                (south, west, north, east) in WGS84 — filters to nodes
                                 intersecting this envelope.
            columns:             SQL select list. Must include `geometri` for geometry output.
            limit:                max rows to return.
            srs:                  EPSG code for the returned geometry (default 4326/WGS84).
        """
        clauses = []
        if beliggenhedskommune is not None:
            clauses.append(f"beliggenhedskommune = {int(beliggenhedskommune)}")
        if krydspunktsnummer is not None:
            clauses.append(f"krydspunktsnummer = '{self._escape(krydspunktsnummer)}'")
        if primaerpunkt is not None:
            clauses.append(f"primaerpunkt = {bool(primaerpunkt)}")
        if blindt_punkt is not None:
            clauses.append(f"blindt_punkt = {bool(blindt_punkt)}")
        if planstatus_kode is not None:
            clauses.append(f"planstatus_kode = {int(planstatus_kode)}")
        if bbox is not None:
            south, west, north, east = bbox
            clauses.append(
                f"ST_Intersects(geometri, ST_MakeEnvelope({west}, {south}, {east}, {north}, 4326))"
            )

        sql = f"SELECT {columns} FROM {NODE_TABLE}"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += f" LIMIT {int(limit)}"

        data = self._fetch(sql, srs=srs)
        return self._parse(data)

    @staticmethod
    def to_geojson(nodes: list[Node]) -> dict:
        return {"type": "FeatureCollection", "features": [n.to_geojson_feature() for n in nodes]}

    @staticmethod
    def to_dicts(nodes: list[Node]) -> list[dict]:
        return [asdict(n) for n in nodes]

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
    def _parse(payload: dict) -> list[Node]:
        features = payload.get("features", [])
        nodes = []
        for feat in features:
            props = dict(feat.get("properties", {}) or {})
            krydspunktsnummer = props.pop("krydspunktsnummer", None)
            beliggenhedskommune = props.pop("beliggenhedskommune", None)
            primaerpunkt = props.pop("primaerpunkt", None)
            blindt_punkt = props.pop("blindt_punkt", None)
            afm_krydspunkt = props.pop("afm_krydspunkt", None)
            nodes.append(
                Node(
                    krydspunktsnummer=krydspunktsnummer,
                    beliggenhedskommune=beliggenhedskommune,
                    primaerpunkt=primaerpunkt,
                    blindt_punkt=blindt_punkt,
                    afm_krydspunkt=afm_krydspunkt,
                    geometry=feat.get("geometry", {}),
                    extra=props,
                )
            )
        return nodes


# ---------------------------------------------------------------------- #
# CLI
# ---------------------------------------------------------------------- #

def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Fetch Danish bike-node-network points (GeoFA theme 5608) from GeoFA."
    )
    parser.add_argument("--beliggenhedskommune", type=int, default=None, help="kommunekode, e.g. 461")
    parser.add_argument("--krydspunktsnummer", default=None, help="signed node number, e.g. 41")
    parser.add_argument("--primaerpunkt", type=lambda v: v.lower() in ("1", "true", "yes"), default=None)
    parser.add_argument("--blindt-punkt", dest="blindt_punkt", type=lambda v: v.lower() in ("1", "true", "yes"), default=None)
    parser.add_argument("--planstatus", dest="planstatus_kode", type=int, default=None, help="1 = Eksisterende, 2 = Planlagt")
    parser.add_argument("--bbox", help="south,west,north,east (WGS84)")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--out", default="-", help="Output file path, or - for stdout")
    parser.add_argument("--format", choices=["geojson", "json"], default="geojson")
    args = parser.parse_args()

    client = NodeClient()
    bbox = tuple(float(x) for x in args.bbox.split(",")) if args.bbox else None

    nodes = client.get_nodes(
        beliggenhedskommune=args.beliggenhedskommune,
        krydspunktsnummer=args.krydspunktsnummer,
        primaerpunkt=args.primaerpunkt,
        blindt_punkt=args.blindt_punkt,
        planstatus_kode=args.planstatus_kode,
        bbox=bbox,
        limit=args.limit,
    )

    result = client.to_geojson(nodes) if args.format == "geojson" else client.to_dicts(nodes)
    text = json.dumps(result, ensure_ascii=False, indent=2)

    if args.out == "-":
        print(text)
    else:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Wrote {len(nodes)} nodes to {args.out}")


if __name__ == "__main__":
    _cli()
