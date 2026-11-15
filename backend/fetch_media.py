#!/usr/bin/env python3
"""Fetch live media for the Geospatial Intelligence Tracker.

Writes, under an output root (default "."):
  data/news.json     GDELT geolocated news events, rolling 24 h
  data/wires.json    RSS headlines from outlets in media_sources.json, tagged by region
  data/streams.json  live streams and webcams, with a reachability check
  data/imagery.json  index of daily NASA GIBS true-color images per region
  media/imagery/<region>.jpg

Headlines are stored with title, outlet, time and link only; no article text.
Every section keeps its previous output if its fetch fails. Standard library only.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_feeds import http_get  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
GDELT_LAST = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
GDELT_FILE = "http://data.gdeltproject.org/gdeltv2/{stamp}.export.CSV.zip"
GDELT_WINDOW_FILES = 4      # 4 x 15 min = the past hour each run
NEWS_KEEP_HOURS = 24
NEWS_MAX = 3000
WIRE_ITEMS_PER_OUTLET = 15
GIBS = ("https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?SERVICE=WMS&REQUEST=GetMap&VERSION=1.1.1"
        "&LAYERS={layer}&SRS=EPSG:4326&BBOX={w},{s},{e},{n}&WIDTH={W}&HEIGHT={H}&FORMAT=image/jpeg&TIME={date}")

CAMEO_ROOT = {
    "01": "Public statement", "02": "Appeal", "03": "Intent to cooperate", "04": "Consultation",
    "05": "Diplomatic cooperation", "06": "Material cooperation", "07": "Aid", "08": "Concession",
    "09": "Investigation", "10": "Demand", "11": "Disapproval", "12": "Rejection", "13": "Threat",
    "14": "Protest", "15": "Force posture", "16": "Reduced relations", "17": "Coercion",
    "18": "Assault", "19": "Fighting", "20": "Mass violence",
}
QUAD = {"1": "Verbal cooperation", "2": "Material cooperation", "3": "Verbal conflict", "4": "Material conflict"}


def now_utc():
    return datetime.now(timezone.utc)


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, separators=(",", ":"), ensure_ascii=False)


# ---------------- GDELT geolocated news ----------------
def slug_title(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    segs = [s for s in path.split("/") if s]
    for seg in reversed(segs):
        seg = re.sub(r"\.(s?html?|php|aspx?|cms)$", "", seg, flags=re.I)
        words = [w for w in re.split(r"[-_+]+", seg) if w and not re.fullmatch(r"[0-9a-f]{6,}|\d+|[a-z]?\d{4,}[a-z0-9]*", w, re.I)]
        if len(words) >= 3:
            t = " ".join(words)
            return (t[0].upper() + t[1:])[:160]
    return ""


def parse_gdelt_rows(text: str, stamp_ms=None):
    """Return {url: event} for root events with city-level locations."""
    out = {}
    for line in text.splitlines():
        c = line.split("\t")
        if len(c) < 61 or c[25] != "1" or c[51] not in ("3", "4"):
            continue
        try:
            lat, lon = float(c[56]), float(c[57])
            mentions = int(c[31] or 0)
        except ValueError:
            continue
        url = c[60].strip()
        if not url.startswith("http"):
            continue
        prev = out.get(url)
        if prev and prev["mentions"] >= mentions:
            continue
        root = c[28][:2]
        place = c[52]
        title = slug_title(url) or f"{CAMEO_ROOT.get(root, 'Event')} – {place}"
        added = c[59]
        try:
            t = int(datetime.strptime(added, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).timestamp() * 1000)
        except ValueError:
            t = stamp_ms
        out[url] = {
            "id": f"GDELT-{c[0]}", "src": "GDELT", "cat": CAMEO_ROOT.get(root, "Event"), "quad": QUAD.get(c[29], ""),
            "conflict": c[29] in ("3", "4"), "title": title, "place": place, "country": c[53],
            "lat": round(lat, 4), "lon": round(lon, 4), "t": t, "url": url,
            "domain": urlparse(url).netloc.replace("www.", ""), "mentions": mentions,
            "tone": round(float(c[34] or 0), 1),
        }
    return out


def fetch_news(previous, fetch=http_get):
    last = fetch(GDELT_LAST).decode("utf-8", "replace")
    m = re.search(r"/(\d{14})\.export\.CSV\.zip", last)
    if not m:
        raise ValueError("GDELT lastupdate.txt has no export file")
    latest = datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    merged, files_ok, errors = {}, 0, []
    for i in range(GDELT_WINDOW_FILES):
        stamp = (latest - timedelta(minutes=15 * i)).strftime("%Y%m%d%H%M%S")
        try:
            z = zipfile.ZipFile(io.BytesIO(fetch(GDELT_FILE.format(stamp=stamp))))
            rows = parse_gdelt_rows(z.read(z.namelist()[0]).decode("utf-8", "replace"))
            for u, e in rows.items():
                if u not in merged or merged[u]["mentions"] < e["mentions"]:
                    merged[u] = e
            files_ok += 1
        except Exception as exc:
            errors.append(f"{stamp}: {type(exc).__name__}")
    if not files_ok:
        raise RuntimeError("no GDELT files could be read: " + "; ".join(errors))
    cutoff = int((now_utc() - timedelta(hours=NEWS_KEEP_HOURS)).timestamp() * 1000)
    for e in (previous or {}).get("events", []):
        if e.get("t") and e["t"] >= cutoff and e["url"] not in merged:
            merged[e["url"]] = e
    events = sorted(merged.values(), key=lambda e: (-e["mentions"], -(e["t"] or 0)))[:NEWS_MAX]
    return {"generated": now_utc().isoformat(timespec="seconds"), "window_hours": NEWS_KEEP_HOURS,
            "latest_file": latest.isoformat(timespec="seconds"), "files_read": files_ok,
            "ok": True, "error": "; ".join(errors) or None, "events": events}


# ---------------- RSS / Atom wires ----------------
def _local(tag):
    return tag.rsplit("}", 1)[-1].lower()


def _text(el):
    return unescape(re.sub(r"<[^>]+>", "", "".join(el.itertext()))).strip() if el is not None else ""


def _date_ms(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return int(d.timestamp() * 1000)


def parse_feed(raw: bytes):
    """Parse RSS 2.0, RSS 1.0 (RDF) or Atom into [{title, url, t}] newest first."""
    root = ET.fromstring(raw)
    items = [el for el in root.iter() if _local(el.tag) in ("item", "entry")]
    out = []
    for it in items:
        fields = {}
        for ch in it:
            name = _local(ch.tag)
            if name == "link" and ch.get("href") and ch.get("rel", "alternate") == "alternate":
                fields.setdefault("link", ch.get("href"))
            elif name not in fields:
                fields[name] = ch
        title = _text(fields.get("title"))
        link = fields.get("link")
        link = link if isinstance(link, str) else _text(link)
        if not link and fields.get("guid") is not None and _text(fields["guid"]).startswith("http"):
            link = _text(fields["guid"])
        date = None
        for k in ("pubdate", "date", "updated", "published", "issued"):
            if fields.get(k) is not None:
                date = _date_ms(_text(fields[k]))
                if date:
                    break
        if title and link and link.startswith("http"):
            out.append({"title": title[:220], "url": link, "t": date})
    out.sort(key=lambda x: -(x["t"] or 0))
    return out


def fetch_wires(cfg, previous, fetch=http_get):
    prev_items = {}
    for it in (previous or {}).get("items", []):
        prev_items.setdefault(it["outlet_id"], []).append(it)
    prev_src = {s["id"]: s for s in (previous or {}).get("sources", [])}
    items, sources = [], []
    for w in cfg["wires"]:
        st = {"id": w["id"], "name": w["name"], "regions": w["regions"], "ok": False, "stale": False,
              "count": 0, "fetched": None, "error": None}
        try:
            got = parse_feed(fetch(w["url"]))[:WIRE_ITEMS_PER_OUTLET]
            if not got:
                raise ValueError("feed had no items")
            for g in got:
                items.append(dict(g, outlet_id=w["id"], outlet=w["name"], regions=w["regions"]))
            st.update(ok=True, count=len(got), fetched=now_utc().isoformat(timespec="seconds"))
        except Exception as exc:
            kept = prev_items.get(w["id"], [])
            items.extend(kept)
            st.update(stale=bool(kept), count=len(kept), fetched=prev_src.get(w["id"], {}).get("fetched"),
                      error=f"{type(exc).__name__}: {str(exc)[:120]}")
        sources.append(st)
    items.sort(key=lambda x: -(x["t"] or 0))
    return {"generated": now_utc().isoformat(timespec="seconds"), "sources": sources, "items": items}


# ---------------- streams ----------------
def fetch_streams(cfg, fetch=http_get):
    out = []
    for s in cfg["streams"]:
        rec = dict(s, ok=False, checked=now_utc().isoformat(timespec="seconds"), error=None)
        try:
            fetch(s["url"])
            rec["ok"] = True
        except Exception as exc:
            rec["error"] = f"{type(exc).__name__}: {str(exc)[:80]}"
        out.append(rec)
    return {"generated": now_utc().isoformat(timespec="seconds"), "items": out}


# ---------------- GIBS imagery ----------------
def image_size(box, width):
    w, s, e, n = box
    h = max(160, round(width * (n - s) / (e - w)))
    return width, h


def looks_blank(jpeg: bytes, w: int, h: int) -> bool:
    """GIBS returns a tiny near-uniform JPEG when a layer has no data for that date."""
    return not jpeg.startswith(b"\xff\xd8") or len(jpeg) < max(6000, w * h * 0.03)


def fetch_imagery(cfg, previous, out_root, fetch=http_get, today=None):
    date = ((today or now_utc().date()) - timedelta(days=1)).isoformat()
    if previous and previous.get("date") == date and all(
            os.path.exists(os.path.join(out_root, r["file"])) for r in previous.get("regions", {}).values()):
        return previous, False  # already have yesterday's images
    regions, errors = {}, []
    for reg in cfg["imagery"]["regions"]:
        W, H = image_size(reg["box"], reg["width"])
        w, s, e, n = reg["box"]
        for layer in cfg["imagery"]["layers"]:
            try:
                img = fetch(GIBS.format(layer=layer, w=w, s=s, e=e, n=n, W=W, H=H, date=date))
            except Exception as exc:
                errors.append(f"{reg['id']}/{layer}: {type(exc).__name__}")
                continue
            if looks_blank(img, W, H):
                continue
            rel = f"media/imagery/{reg['id']}.jpg"
            os.makedirs(os.path.join(out_root, "media", "imagery"), exist_ok=True)
            with open(os.path.join(out_root, rel), "wb") as fh:
                fh.write(img)
            regions[reg["id"]] = {"name": reg["name"], "box": reg["box"], "width": W, "height": H,
                                  "file": rel, "layer": layer, "bytes": len(img)}
            break
        else:
            errors.append(f"{reg['id']}: no layer had imagery")
    if not regions:
        if previous:
            return dict(previous, error="; ".join(errors)[:300]), False
        raise RuntimeError("; ".join(errors)[:300])
    return {"generated": now_utc().isoformat(timespec="seconds"), "date": date,
            "source": "NASA GIBS / Worldview corrected-reflectance true color",
            "regions": regions, "error": "; ".join(errors)[:300] or None}, True


# ---------------- run ----------------
def main(out_root="."):
    cfg = load_json(os.path.join(HERE, "media_sources.json"))
    p = lambda name: os.path.join(out_root, "data", name)  # noqa: E731
    status = {}

    def section(name, fn):
        try:
            fn()
            status[name] = "OK"
        except Exception as exc:
            status[name] = f"FAIL {type(exc).__name__}: {str(exc)[:120]} (kept previous)"

    section("news", lambda: save_json(p("news.json"), fetch_news(load_json(p("news.json")))))
    section("wires", lambda: save_json(p("wires.json"), fetch_wires(cfg, load_json(p("wires.json")))))
    section("streams", lambda: save_json(p("streams.json"), fetch_streams(cfg)))

    def imagery():
        data, new = fetch_imagery(cfg, load_json(p("imagery.json")), out_root)
        save_json(p("imagery.json"), data)
        status["imagery_new"] = new
    section("imagery", imagery)

    for k, v in status.items():
        print(f"{k:<12} {v}")
    news, wires = load_json(p("news.json"), {}), load_json(p("wires.json"), {})
    print(f"news events: {len(news.get('events', []))}; wire items: {len(wires.get('items', []))}; "
          f"wire outlets ok: {sum(s['ok'] for s in wires.get('sources', []))}/{len(wires.get('sources', []))}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
