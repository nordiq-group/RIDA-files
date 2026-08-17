# mcp

GeoFA (where the bike services lie) - has a MCP

Wire it up and get going.

If can be talked to in any language of the world.

If you are used to reading skills go here: 

https://github.com/nordiq-group/geofa-mcp/tree/main/skills


Otherwise you can ask the following:

## API query strings
```
Show me the simplest API query for nodes in Denmark.
```
```
Show me the simples API query for edges in Denmark.
```
```
Show me a query for All nodes in Tønder (municpality).
```

## Postman files

If you are used to working with postman its easy:

1) Download a postman file for nodes.
2) Download a postmad file for eedges.



5) Show me a query for All nodes in Tønder (municpality).


2"Can you make a python3 module that pulls data from the bicycle nodes?" => Krydspunkter
3...


**Through the MCP server**, this maps to the `query_geofa` tool, with parameters:
- `sql` (required) — the SELECT statement, sent as `q`
- `format` — geojson (default), excel, csv, ogr/ESRI Shapefile, ogr/MapInfo File, ogr/GPKG, ogr/GML
- `srs` — EPSG code; the tool defaults this to 4326 (WGS84) rather than the API's own default of 3857
- `geoformat` — geometry encoding when format is excel/csv (geojson or wkt)
- `allstr` — return all columns as text
- `lifetime` — cache duration in seconds (default 0 = no cache)
- `use_test_env` — use test environment instead of production

⚠️ If you ever hit the endpoint directly (curl, browser, a script outside the MCP tool) rather than through `query_geofa`, remember to set `srs=4326` explicitly — otherwise coordinates come back in metres (EPSG:3857), which will silently break spatial-snapping logic (e.g. in `topology-extraction`) expecting degrees.

*Note: the GeoFA MCP server was unresponsive when this guide was written, so exact column names beyond `geometri`, `kommunekode`, and `objectid` haven't been verified against the live spec yet — confirm with `list_fkg_tables()` / `search_spec()` once the server is back up.*
