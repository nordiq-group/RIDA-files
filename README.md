# Connecting to the GeoFA Ecosystem — Bike Nodes & Bike-Node Routes

## What GeoFA is

GeoFA (Geografisk Administrationsgrundlag) is the Danish national platform for municipally-maintained 
outdoor/recreation and facility geodata, built on the FKG (Fælles KortGrundlag) data model. 
It's read via a SQL-style HTTP API that lets you `SELECT` from tables named `fkg.t_<theme>_<shortname>`.

## Two themes for cycle-nodes and -routes

| Theme | Table | Geometry | Content                                                      |
|---|---|---|--------------------------------------------------------------|
| 5608 | `fkg.t_5608_cykelkrydspunkter` | Point | Numbered cycle-node network waypoints (cykelkrydspunkter)    |
| 5609 | `fkg.t_5609_cykelkrydspunktsstraekninger` | LineString | Signposted stretches connecting two nodes (cykelstrækninger) |

**Important quirk:** 5609 has no `from_node`/`to_node` column. 
The connection between a stretch and its two endpoint nodes has 
to be derived spatially —
snap each line's start/end vertex to the nearest 5608 point. 

<!-- This is what the `topology-extraction` of the geo-fa MCP skill handles. -->

## How the API works

The GeoFA SQL API is a plain HTTP GET endpoint with query parameters — 
not a JSON body, not a typical REST resource path.

You build a URL and the SQL itself is one of the query params. 

It's *read-only*: only `SELECT` is accepted, nothing that writes or deletes. 
PostGIS functions work inline — `ST_Length`, `ST_Within`, `ST_MakeEnvelope`, etc.

**Base URL**

``https://geofa.geodanmark.dk/api/v2/sql/fkg``

**Parameters**

| Param | Meaning |
|---|---|
| `q` | **Required.** The SQL SELECT string. |
| `srs` | EPSG code for returned geometry's projection. **API default is 3857** (Web Mercator) — for plain lat/lon you must ask for `4326` explicitly. |
| `format` | `geojson` (default), `excel`, `csv`, `ogr/ESRI Shapefile`, `ogr/MapInfo File`, `ogr/GPKG`, `ogr/GML` |
| `geoformat` | Only relevant when `format=excel` or `csv` — geometry encoding: `geojson` or `wkt` |
| `allstr` | If set, every column is returned as text type regardless of its real type |
| `lifetime` | Seconds the result should be cached before returning (default `0` = no caching) |
| `base64` | Marks that `q` is base64-encoded — a workaround for firewalls with overzealous threat detection on raw SQL in a URL |

**Simplest Working example** — All bike nodes in Denmark, as lat/lon GeoJSON:
```
https://geofa.geodanmark.dk/api/v2/sql/fkg?q=SELECT+krydspunktsnummer,geometri+FROM+fkg.t_5608_cykelkrydspunkter&srs=4326&format=geojson
```

**Scoped to a municipality:** — bike nodes in Varde (municipal code = 573), as lat/lon GeoJSON:
```
https://geofa.geodanmark.dk/api/v2/sql/fkg?q=SELECT+krydspunktsnummer,geometri+FROM+fkg.t_5608_cykelkrydspunkter+WHERE+kommunekode=573&srs=4326&format=geojson
```



Same query but for routes

```
https://geofa.geodanmark.dk/api/v2/sql/fkg?q=SELECT+geometri+FROM+fkg.t_5609_cykelkrydspunktsstraekninger&srs=4326&format=geojson
```

```
https://geofa.geodanmark.dk/api/v2/sql/fkg?q=SELECT+geometri+FROM+fkg.t_5609_cykelkrydspunktsstraekninger+WHERE+kommunekode=573&srs=4326&format=geojson
```

## Demo queries

**1. 500 cycle nodes in a municipality**
```sql
SELECT krydspunktsnummer, geometri
FROM fkg.t_5608_cykelkrydspunkter
WHERE kommunekode = 573  -- Varde
LIMIT 500
```

**2. 500 route stretches in the same municipality, with length**
```sql
SELECT objectid, ST_Length(geometri) AS length_m, geometri
FROM fkg.t_5609_cykelkrydspunktsstraekninger
WHERE kommunekode = 573
ORDER BY length_m DESC
LIMIT 500
```

**3. Nodes inside a bounding box (e.g. Blåvand–Skagen corridor slice)**
```sql
SELECT krydspunktsnummer, geometri
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
