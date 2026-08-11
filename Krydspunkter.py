
Geofa cycle nodes · PY
"""
geofa_cycle_nodes.py
 
Fetch Danish cycle-node-network waypoints ("cykelknudepunkter") from
OpenStreetMap via the Overpass API.
 
Denmark's regional cycle node network is mapped in OSM using the same
"node network" tagging scheme used across NL/BE/DK: individual
waypoints carry a `rcn_ref` (regional cycle network reference number)
and/or `network=rcn`. This module queries Overpass for those nodes,
either within a bounding box or within a named municipality
(kommune), and returns them as plain Python objects, GeoJSON, or
plain dicts (e.g. for pandas.DataFrame(...)).
 
Example
-------
    from geofa_cycle_nodes import CycleNodeClient
 
    client = CycleNodeClient()
    nodes = client.get_by_municipality("Tønder Kommune")
    geojson = client.to_geojson(nodes)
 
CLI
---
    python3 geofa_cycle_nodes.py --municipality "Tønder Kommune" --out nodes.geojson
    python3 geofa_cycle_nodes.py --bbox 54.9,8.5,55.1,8.8 --format json --out nodes.json
"""
 
from __future__ import annotations
 
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Iterable, Optional
 
DEFAULT_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
 
 
class OverpassError(RuntimeError):
    """Raised when all configured Overpass endpoints fail."""
 
 
@dataclass
class CycleNode:
    """A single numbered cycle-node-network waypoint."""
 
    id: int
    ref: str
    lat: float
    lon: float
    name: Optional[str] = None
    network: Optional[str] = None
    tags: dict = field(default_factory=dict)
 
    def to_geojson_feature(self) -> dict:
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [self.lon, self.lat]},
            "properties": {
                "id": self.id,
                "ref": self.ref,
                "name": self.name,
                "network": self.network,
                **self.tags,
            },
        }
 
 
class CycleNodeClient:
    """Client for fetching Danish cycle-node-network points via Overpass."""
 
    def __init__(
        self,
        endpoints: Iterable[str] = DEFAULT_ENDPOINTS,
        timeout: int = 30,
        retries: int = 2,
        user_agent: str = "geofa-cycle-nodes/1.0 (personal research use)",
    ):
        self.endpoints = list(endpoints)
        self.timeout = timeout
        self.retries = retries
        self.user_agent = user_agent
 
    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
 
    def get_by_bbox(
        self,
        south: float,
        west: float,
        north: float,
        east: float,
        limit: Optional[int] = None,
    ) -> list[CycleNode]:
        """Fetch nodes within a WGS84 bounding box (south, west, north, east)."""
        area_clause = f"({south},{west},{north},{east})"
        query = self._build_query(area_clause=area_clause)
        return self._run(query, limit)
 
    def get_by_municipality(self, name: str, limit: Optional[int] = None) -> list[CycleNode]:
        """Fetch nodes within a named Danish municipality, e.g. 'Tønder Kommune'."""
        if "kommune" not in name.lower():
            name = f"{name} Kommune"
        area_setup = f'area["name"="{name}"]["boundary"="administrative"]->.searchArea;'
        query = self._build_query(area_clause="(area.searchArea)", area_setup=area_setup)
        return self._run(query, limit)
 
    @staticmethod
    def to_geojson(nodes: list[CycleNode]) -> dict:
        return {"type": "FeatureCollection", "features": [n.to_geojson_feature() for n in nodes]}
 
    @staticmethod
    def to_dicts(nodes: list[CycleNode]) -> list[dict]:
        return [asdict(n) for n in nodes]
 
    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
 
    @staticmethod
    def _build_query(area_clause: str, area_setup: str = "") -> str:
        return f"""
[out:json][timeout:60];
{area_setup}
(
  node["rcn_ref"]{area_clause};
  node["network"="rcn"]{area_clause};
);
out body;
""".strip()
 
    def _run(self, query: str, limit: Optional[int]) -> list[CycleNode]:
        data = self._fetch(query)
        nodes = self._parse(data)
        nodes.sort(key=lambda n: (n.ref or ""))
 
        seen: set[int] = set()
        unique: list[CycleNode] = []
        for n in nodes:
            if n.id in seen:
                continue
            seen.add(n.id)
            unique.append(n)
 
        return unique[:limit] if limit else unique
 
    def _fetch(self, query: str) -> dict:
        payload = urllib.parse.urlencode({"data": query}).encode("utf-8")
        last_err: Optional[Exception] = None
 
        for endpoint in self.endpoints:
            for attempt in range(self.retries + 1):
                try:
                    req = urllib.request.Request(
                        endpoint,
                        data=payload,
                        method="POST",
                        headers={"User-Agent": self.user_agent},
                    )
                    with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                        return json.loads(resp.read().decode("utf-8"))
                except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                    last_err = exc
                    time.sleep(1.5 * (attempt + 1))
 
        raise OverpassError(f"Failed to fetch from all Overpass endpoints: {last_err}")
 
    @staticmethod
    def _parse(data: dict) -> list[CycleNode]:
        nodes = []
        for el in data.get("elements", []):
            if el.get("type") != "node":
                continue
            tags = el.get("tags", {}) or {}
            ref = tags.get("rcn_ref") or tags.get("ref") or ""
            nodes.append(
                CycleNode(
                    id=el["id"],
                    ref=str(ref),
                    lat=el["lat"],
                    lon=el["lon"],
                    name=tags.get("name"),
                    network=tags.get("network"),
                    tags=tags,
                )
            )
        return nodes
 
 
# ---------------------------------------------------------------------- #
# CLI
# ---------------------------------------------------------------------- #
 
def _cli() -> None:
    import argparse
 
    parser = argparse.ArgumentParser(description="Fetch Danish cycle node network points (cykelknudepunkter).")
    parser.add_argument("--municipality", help='e.g. "Tønder Kommune"')
    parser.add_argument("--bbox", help="south,west,north,east (WGS84)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", default="-", help="Output file path, or - for stdout")
    parser.add_argument("--format", choices=["geojson", "json"], default="geojson")
    args = parser.parse_args()
 
    client = CycleNodeClient()
 
    if args.bbox:
        s, w, n, e = (float(x) for x in args.bbox.split(","))
        nodes = client.get_by_bbox(s, w, n, e, limit=args.limit)
    elif args.municipality:
        nodes = client.get_by_municipality(args.municipality, limit=args.limit)
    else:
        parser.error("Provide --municipality or --bbox")
        return
 
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
 
