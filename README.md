# Connecting to the GeoFA Ecosystem — Bike Nodes & Bike-Node Routes

## What GeoFA is

GeoFA (Geografisk Administrationsgrundlag) is the Danish national platform for 
municipally-maintained outdoor/recreation and facility geodata, built on the FKG 
(Fælles KortGrundlag) data model.

It's read via a SQL-style HTTP API that lets you `SELECT` from tables named `fkg.t_<theme>_<shortname>`.

## The two themes for bike nodes & lines

| Theme | Table | Geometry | Content                                              |
|---|---|---|------------------------------------------------------|
| 5608 | `fkg.t_5608_cykelkrydspunkter` | Point | Numbered cycle-node network waypoints (krydspunkter) |
| 5609 | `fkg.t_5609_cykelkrydspunktsstraekninger` | LineString | Signposted stretches connecting two nodes            |

**Important quirk:** 5609 has no `from_node` / `to_node` column. 
The connection between a stretch and its two endpoint nodes has to be derived spatially — 
snap each line's start/end vertex to the nearest 5608 point. 
This is what the `topology-extraction` skill handles.

## How the API works

The API is a single read-only SQL endpoint. You send a `SELECT` 
statement against `fkg.t_XXXX_...`, and it returns 
GeoJSON by default (or CSV / Excel / Shapefile / GPKG / GML) 
with geometry reprojected to whatever `srs` you ask for (default EPSG:4326). 
PostGIS functions work inline — `ST_Length`, `ST_Within`, `ST_MakeEnvelope`, etc.

Through the `geofa` MCP server this maps to the `query_geofa` tool, with parameters:
- `sql` (required) — the SELECT statement
- `format` — geojson (default), excel, csv, ogr/ESRI Shapefile, ogr/MapInfo File, ogr/GPKG, ogr/GML
- `srs` — EPSG code, default 4326 (WGS84); 3857 for Web Mercator
- `geoformat` — geometry encoding when format is excel/csv (geojson or wkt)
- `allstr` — return all columns as text
- `lifetime` — cache duration in seconds (default 0 = no cache)
- `use_test_env` — use test environment instead of production

## Demo queries

**1. All cycle nodes in a municipality**
```sql
SELECT knudepunktsnummer, geometri
FROM fkg.t_5608_cykelkrydspunkter
WHERE kommunekode = 573  -- Varde
LIMIT 500
```

**2. All route stretches in the same municipality, with length**
```sql
SELECT objectid, ST_Length(geometri) AS length_m, geometri
FROM fkg.t_5609_cykelkrydspunktsstraekninger
WHERE kommunekode = 573
ORDER BY length_m DESC
LIMIT 500
```

**3. Nodes inside a bounding box (e.g. Blåvand–Skagen corridor slice)**
```sql
SELECT knudepunktsnummer, geometri
FROM fkg.t_5608_cykelkrydspunkter
WHERE ST_Within(geometri, ST_MakeEnvelope(8.0, 55.4, 9.2, 56.2, 4326))
```

**4. Count nodes per municipality**
```sql
SELECT kommunekode, COUNT(*) AS node_count
FROM fkg.t_5608_cykelkrydspunkter
GROUP BY kommunekode
ORDER BY node_count DESC
```

**5. Longest 10 stretches nationally (sanity-check for topology extraction)**
```sql
SELECT objectid, ST_Length(geometri) AS length_m
FROM fkg.t_5609_cykelkrydspunktsstraekninger
ORDER BY length_m DESC
LIMIT 10
```

---

*Note: the GeoFA MCP server was unresponsive when this guide was written, so exact column names beyond `geometri`, `kommunekode`, and `objectid` haven't been verified against the live spec yet — confirm with `list_fkg_tables()` / `search_spec()` once the server is back up.*
