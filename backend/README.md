# Feed backend

Hourly pipeline that keeps the Geospatial Intelligence Tracker's map current.

| Step | Where | What |
|---|---|---|
| Fetch | GitHub Actions (`.github/workflows/fetch-feeds.yml`, minute 17 each hour) | `backend/fetch_feeds.py` pulls four public feeds and writes `data/feeds.json` |
| Store | `feeds-data` branch | One force-pushed commit holding the latest `data/feeds.json` (no history growth) |
| Deliver | Claude scheduled task | Copies the file into the published tracker site, which reads it on load |

## Sources
- USGS earthquakes M2.5+, past 7 days (GeoJSON)
- NASA EONET open natural events, past 30 days (JSON)
- NWS active U.S. weather alerts with polygons (GeoJSON; zone-only alerts are skipped)
- NASA FIRMS VIIRS active fires, past 24 h, high-confidence only, strongest 2,500 by fire radiative power (CSV)

If a source fails, its events from the previous run are kept and marked stale in `sources[]`. The job fails only if no data at all is available.

## Run locally
```
python -m unittest backend/test_fetch_feeds.py
python backend/fetch_feeds.py data/feeds.json
```
Run the workflow on demand from the Actions tab with **Run workflow**.
