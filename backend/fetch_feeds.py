#!/usr/bin/env python3
"""Fetch open-source GEOINT feeds and normalize them into one JSON file.

Output schema (data/feeds.json):
{
  "generated": ISO-8601 UTC,
  "sources": [{"id","name","url","ok","stale","count","fetched","error"}],
  "events":  [{"id","src","cat","title","lon","lat","t","mag","magUnit","url","severity"}]
}
`t` is epoch milliseconds (UTC). If a source fails, its events from the
previous run are kept and the source is marked stale, so one outage never
blanks the map. Standard library only.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

USER_AGENT = "MAXIMUS-GEOINT-Tracker/1.0 (github.com/Macrovola/MAXIMUS)"
TIMEOUT = 60
FIRMS_MAX = 2500  # strongest high-confidence detections kept, to bound file size

SOURCES = {
    "usgs": {
        "name": "USGS earthquakes M2.5+ (7 days)",
        "url": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson",
    },
    "eonet": {
        "name": "NASA EONET open natural events (30 days)",
        "url": "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&days=30",
    },
    "nws": {
        "name": "NWS active U.S. weather alerts",
        "url": "https://api.weather.gov/alerts/active?status=actual",
    },
    "gdacs": {
        "name": "GDACS global disaster alerts",
        "url": "https://www.gdacs.org/xml/rss.xml",
    },
    "firms": {
        "name": "NASA FIRMS active fires (24 h, high confidence)",
        "url": "https://firms.modaps.eosdis.nasa.gov/active_fire/",
        # Tried in order; the first file with data rows is used (satellite files can be empty during outages).
        "urls": [
            "https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-20-viirs-c2/csv/J1_VIIRS_C2_Global_24h.csv",
            "https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-21-viirs-c2/csv/J2_VIIRS_C2_Global_24h.csv",
            "https://firms.modaps.eosdis.nasa.gov/data/active_fire/suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_Global_24h.csv",
            "https://firms.modaps.eosdis.nasa.gov/data/active_fire/modis-c6.1/csv/MODIS_C6_1_Global_24h.csv",
        ],
    },
}


# ---------- helpers ----------
def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/geo+json, application/json, text/csv, */*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def iso_ms(s):
    if s is None or s == "":
        return None
    if isinstance(s, (int, float)):
        return int(s if s > 1e11 else s * 1000)
    s = str(s).strip().replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return int(d.timestamp() * 1000)


def centroid(geom):
    """Point coordinates, or the mean vertex of a line/polygon (adequate for map markers)."""
    if not geom:
        return None
    t, c = geom.get("type"), geom.get("coordinates")
    if t == "Point" and c:
        return c[0], c[1]
    pts = []

    def walk(x):
        if isinstance(x, (list, tuple)) and x and isinstance(x[0], (int, float)):
            pts.append(x)
        elif isinstance(x, (list, tuple)):
            for y in x:
                walk(y)

    if t == "GeometryCollection":
        for g in geom.get("geometries") or []:
            walk(g.get("coordinates"))
    else:
        walk(c)
    if not pts:
        return None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def ev(src, eid, cat, title, lon, lat, t, mag=None, mag_unit="", url="", severity=None):
    if lon is None or lat is None or not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None
    return {
        "id": f"{src}-{eid}", "src": src, "cat": str(cat)[:80], "title": str(title)[:200],
        "lon": round(float(lon), 4), "lat": round(float(lat), 4), "t": t,
        "mag": mag, "magUnit": mag_unit or "", "url": url or "", "severity": severity,
    }


# ---------- parsers (pure; tested with fixtures) ----------
def parse_usgs(raw: bytes):
    out = []
    for f in json.loads(raw).get("features", []):
        p = f.get("properties") or {}
        c = centroid(f.get("geometry"))
        if not c:
            continue
        typ = (p.get("type") or "earthquake").capitalize()
        e = ev("USGS", f.get("id"), typ, p.get("title") or p.get("place"), c[0], c[1], p.get("time"),
               p.get("mag"), p.get("magType") or "M", p.get("url"), p.get("alert"))
        if e:
            out.append(e)
    return out


def parse_eonet(raw: bytes):
    out = []
    for e in json.loads(raw).get("events", []):
        geoms = e.get("geometry") or []
        if not geoms:
            continue
        last = geoms[-1]
        c = centroid({"type": last.get("type"), "coordinates": last.get("coordinates")})
        if not c:
            continue
        cats = e.get("categories") or [{}]
        srcs = e.get("sources") or [{}]
        item = ev("NASA EONET", e.get("id"), cats[0].get("title") or "Natural event", e.get("title"),
                  c[0], c[1], iso_ms(last.get("date")), last.get("magnitudeValue"),
                  last.get("magnitudeUnit") or "", srcs[0].get("url") or e.get("link"))
        if item:
            out.append(item)
    return out


def parse_nws(raw: bytes):
    out = []
    for f in json.loads(raw).get("features", []):
        c = centroid(f.get("geometry"))  # zone-only alerts have no geometry and are skipped
        if not c:
            continue
        p = f.get("properties") or {}
        e = ev("NWS alerts", p.get("id") or f.get("id"), p.get("event") or "Weather alert",
               p.get("headline") or p.get("event"), c[0], c[1],
               iso_ms(p.get("sent") or p.get("effective")), None, "", p.get("@id") or f.get("id"),
               p.get("severity"))
        if e:
            out.append(e)
    return out


def parse_firms(raw: bytes):
    text = raw.decode("utf-8", "replace").lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text))
    fields = [f.strip().lower() for f in (reader.fieldnames or [])]
    if "latitude" not in fields or "longitude" not in fields:
        raise ValueError(f"not a FIRMS CSV; response starts with {text[:120]!r}")
    reader.fieldnames = fields
    rows, seen = [], {}
    for r in reader:
        conf = (r.get("confidence") or "").strip().lower()
        seen[conf] = seen.get(conf, 0) + 1
        try:
            lat, lon, frp = float(r["latitude"]), float(r["longitude"]), float(r.get("frp") or 0)
        except (KeyError, ValueError, TypeError):
            continue
        rows.append((conf, frp, lat, lon, r))
    if not rows:
        raise ValueError("FIRMS CSV had a header but no data rows")
    # VIIRS uses l/n/h; MODIS uses 0-100. Keep high confidence; fall back to nominal if none.
    def is_high(c):
        return c in ("h", "high") or (c.isdigit() and int(c) >= 80)
    def is_nominal(c):
        return c in ("n", "nominal") or (c.isdigit() and int(c) >= 30)
    keep = [x for x in rows if is_high(x[0])] or [x for x in rows if is_nominal(x[0]) or is_high(x[0])]
    keep.sort(key=lambda x: -x[1])
    out = []
    for conf, frp, lat, lon, r in keep[:FIRMS_MAX]:
        hm = (r.get("acq_time") or "0").strip().zfill(4)
        t = iso_ms(f"{(r.get('acq_date') or '').strip()}T{hm[:2]}:{hm[2:]}:00+00:00")
        e = ev("NASA FIRMS", f"{r.get('acq_date')}-{hm}-{lat:.3f}-{lon:.3f}", "Wildfire / thermal anomaly",
               f"Thermal anomaly, FRP {frp:.1f} MW", lon, lat, t, round(frp, 1), "MW FRP")
        if e:
            out.append(e)
    print(f"  firms: {len(rows)} rows, confidence values {dict(sorted(seen.items())[:10])}, kept {len(out)}")
    return out


GDACS_TYPES = {"EQ": "Earthquake", "TC": "Tropical cyclone", "FL": "Flood", "VO": "Volcano", "DR": "Drought",
               "WF": "Wildfire", "TS": "Tsunami"}


def parse_gdacs(raw: bytes):
    import xml.etree.ElementTree as ET
    out = []
    for item in ET.fromstring(raw).iter("item"):
        f = {}
        for el in item.iter():
            name = el.tag.rsplit("}", 1)[-1].lower()
            if name not in f and (el.text or "").strip():
                f[name] = el.text.strip()
        try:
            lat, lon = float(f["lat"]), float(f["long"])
        except (KeyError, ValueError):
            continue
        etype = f.get("eventtype", "")
        t = None
        if f.get("pubdate"):
            from email.utils import parsedate_to_datetime
            try:
                t = int(parsedate_to_datetime(f["pubdate"]).timestamp() * 1000)
            except (TypeError, ValueError):
                t = None
        e = ev("GDACS", f"{etype}{f.get('eventid', '')}-{f.get('episodeid', '')}", GDACS_TYPES.get(etype, "Disaster alert"),
               f.get("title", "GDACS alert"), lon, lat, t, None, "", f.get("link"), f.get("alertlevel"))
        if e:
            out.append(e)
    return out


PARSERS = {"usgs": parse_usgs, "eonet": parse_eonet, "nws": parse_nws, "gdacs": parse_gdacs, "firms": parse_firms}
SRC_LABEL = {"usgs": "USGS", "eonet": "NASA EONET", "nws": "NWS alerts", "gdacs": "GDACS", "firms": "NASA FIRMS"}


# ---------- run ----------
def build(previous: dict | None, fetch=http_get, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    prev_events = (previous or {}).get("events", [])
    prev_sources = {s["id"]: s for s in (previous or {}).get("sources", [])}
    events, sources = [], []
    for sid, meta in SOURCES.items():
        status = {"id": sid, "name": meta["name"], "url": meta["url"], "ok": False, "stale": False,
                  "count": 0, "fetched": None, "error": None}
        try:
            got, errors = None, []
            for url in meta.get("urls", [meta["url"]]):
                try:
                    got = PARSERS[sid](fetch(url))
                    if got:
                        break
                    errors.append(f"{url.rsplit('/', 1)[-1]}: no events")
                except Exception as exc:
                    errors.append(f"{url.rsplit('/', 1)[-1]}: {type(exc).__name__}: {str(exc)[:80]}")
                    got = None
            if got is None:
                raise RuntimeError("; ".join(errors))
            events.extend(got)
            status.update(ok=True, count=len(got), fetched=now.isoformat(timespec="seconds"))
        except Exception as exc:  # keep last good data for this source
            kept = [e for e in prev_events if e.get("src") == SRC_LABEL[sid]]
            events.extend(kept)
            p = prev_sources.get(sid, {})
            status.update(stale=bool(kept), count=len(kept), fetched=p.get("fetched"),
                          error=f"{type(exc).__name__}: {str(exc)[:160]}")
        sources.append(status)
    return {"generated": now.isoformat(timespec="seconds"), "sources": sources, "events": events}


def main(path="data/feeds.json"):
    previous = None
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                previous = json.load(fh)
        except (OSError, ValueError):
            previous = None
    data = build(previous)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, separators=(",", ":"))
    for s in data["sources"]:
        flag = "OK   " if s["ok"] else ("STALE" if s["stale"] else "FAIL ")
        print(f"{flag} {s['id']:<6} {s['count']:>6}  {s['error'] or ''}")
    print(f"{len(data['events'])} events, {os.path.getsize(path)/1024:.0f} KiB -> {path}")
    # Fail the job only if every source failed and nothing could be kept.
    return 0 if data["events"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "data/feeds.json"))
