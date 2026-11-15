"""Fixture tests for media parsers. Run: python -m unittest discover backend"""
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
import fetch_feeds as ff  # noqa: E402
import fetch_media as fm  # noqa: E402


def gdelt_row(eid, url, root="19", quad="4", geo_type="4", mentions="5", root_event="1", lat="48.0", lon="37.8",
              added="20261115170000", place="Donetsk, Donets'k, Ukraine"):
    c = [""] * 61
    c[0], c[1], c[25], c[26], c[28], c[29], c[31], c[34] = eid, "20261115", root_event, root + "0", root, quad, mentions, "-3.25"
    c[51], c[52], c[53], c[56], c[57], c[59], c[60] = geo_type, place, "UP", lat, lon, added, url
    return "\t".join(c)


class Gdelt(unittest.TestCase):
    def test_filters_dedupes_and_titles(self):
        rows = "\n".join([
            gdelt_row("1", "https://news.example.com/2026/11/15/shelling-hits-power-station-near-donetsk/", mentions="3"),
            gdelt_row("2", "https://news.example.com/2026/11/15/shelling-hits-power-station-near-donetsk/", mentions="9"),
            gdelt_row("3", "https://x.example.org/a/12345678", root="14", quad="3"),
            gdelt_row("4", "https://skip.example.com/country-level-story-here", geo_type="1"),
            gdelt_row("5", "https://skip.example.com/not-root-event-here", root_event="0"),
        ])
        out = fm.parse_gdelt_rows(rows)
        self.assertEqual(len(out), 2)
        e = out["https://news.example.com/2026/11/15/shelling-hits-power-station-near-donetsk/"]
        self.assertEqual(e["id"], "GDELT-2")
        self.assertEqual(e["mentions"], 9)
        self.assertEqual(e["title"], "Shelling hits power station near donetsk")
        self.assertEqual(e["cat"], "Fighting")
        self.assertTrue(e["conflict"])
        self.assertEqual(out["https://x.example.org/a/12345678"]["title"], "Protest – Donetsk, Donets'k, Ukraine")

    def test_fetch_news_window_and_rollover(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("x.export.CSV", gdelt_row("7", "https://a.example.com/troops-mass-near-border-town", added=fm.now_utc().strftime("%Y%m%d%H%M%S")))
        blob = buf.getvalue()
        last = b"1 a http://data.gdeltproject.org/gdeltv2/20261115174500.export.CSV.zip\n"
        calls = []

        def fake(url):
            calls.append(url)
            if url.endswith("lastupdate.txt"):
                return last
            if "20261115170000" in url:
                raise TimeoutError()
            return blob
        prev = {"events": [{"url": "https://old.example.com/x", "t": 0, "mentions": 1},
                           {"url": "https://recent.example.com/y", "t": int(fm.now_utc().timestamp() * 1000), "mentions": 2}]}
        out = fm.fetch_news(prev, fetch=fake)
        self.assertEqual(out["files_read"], 3)
        urls = [e["url"] for e in out["events"]]
        self.assertIn("https://recent.example.com/y", urls)
        self.assertNotIn("https://old.example.com/x", urls)
        self.assertIn("20261115173000.export.CSV.zip", calls[2])


RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>
<item><title>Older &amp; item</title><link>https://e.com/1</link><pubDate>Sat, 14 Nov 2026 10:00:00 GMT</pubDate></item>
<item><title><![CDATA[<b>Newer</b> item]]></title><link>https://e.com/2</link><pubDate>Sun, 15 Nov 2026 10:00:00 +0000</pubDate></item>
</channel></rss>"""
RDF = b"""<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
<item rdf:about="https://d.com/a"><title>RDF headline</title><link>https://d.com/a</link><dc:date>2026-11-15T09:00:00Z</dc:date></item></rdf:RDF>"""
ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Atom headline</title>
<link rel="alternate" href="https://a.com/x"/><updated>2026-11-15T08:00:00Z</updated></entry></feed>"""
GDACS = b"""<?xml version="1.0"?><rss xmlns:geo="http://www.w3.org/2003/01/geo/wgs84_pos#" xmlns:gdacs="http://www.gdacs.org"><channel>
<item><title>Orange earthquake alert in Peru</title><link>https://www.gdacs.org/report.aspx?eventid=1</link>
<pubDate>Sun, 15 Nov 2026 12:00:00 GMT</pubDate><gdacs:eventtype>EQ</gdacs:eventtype><gdacs:alertlevel>Orange</gdacs:alertlevel>
<gdacs:eventid>1</gdacs:eventid><geo:Point><geo:lat>-12.1</geo:lat><geo:long>-77.0</geo:long></geo:Point></item>
<item><title>No location</title></item></channel></rss>"""


class Wires(unittest.TestCase):
    def test_rss_sorted_and_cleaned(self):
        items = fm.parse_feed(RSS)
        self.assertEqual([i["title"] for i in items], ["Newer item", "Older & item"])

    def test_rdf_and_atom(self):
        self.assertEqual(fm.parse_feed(RDF)[0]["url"], "https://d.com/a")
        a = fm.parse_feed(ATOM)[0]
        self.assertEqual((a["title"], a["url"]), ("Atom headline", "https://a.com/x"))

    def test_failed_outlet_keeps_previous(self):
        cfg = {"wires": [{"id": "ok", "name": "OK", "url": "u1", "regions": ["global"]},
                         {"id": "down", "name": "Down", "url": "u2", "regions": ["africa"]}]}
        prev = {"items": [{"outlet_id": "down", "title": "kept", "url": "https://k", "t": 1}],
                "sources": [{"id": "down", "fetched": "2026-11-15T10:00:00+00:00"}]}

        def fake(url):
            if url == "u1":
                return RSS
            raise TimeoutError()
        out = fm.fetch_wires(cfg, prev, fetch=fake)
        down = next(s for s in out["sources"] if s["id"] == "down")
        self.assertTrue(down["stale"])
        self.assertEqual(len(out["items"]), 3)


class Gdacs(unittest.TestCase):
    def test_parse(self):
        e = ff.parse_gdacs(GDACS)
        self.assertEqual(len(e), 1)
        self.assertEqual((e[0]["cat"], e[0]["severity"], e[0]["lat"]), ("Earthquake", "Orange", -12.1))


class Imagery(unittest.TestCase):
    CFG = {"imagery": {"layers": ["BLANK", "GOOD"], "regions": [{"id": "eeurope", "name": "E", "box": [20, 40, 60, 62], "width": 400}]}}

    def test_falls_through_blank_layer_and_skips_when_current(self):
        good = b"\xff\xd8" + b"x" * 20000

        def fake(url):
            return b"\xff\xd8tiny" if "LAYERS=BLANK" in url else good
        with tempfile.TemporaryDirectory() as d:
            data, new = fm.fetch_imagery(self.CFG, None, d, fetch=fake, today=date(2026, 11, 15))
            self.assertTrue(new)
            self.assertEqual(data["date"], "2026-11-14")
            self.assertEqual(data["regions"]["eeurope"]["layer"], "GOOD")
            self.assertEqual(data["regions"]["eeurope"]["height"], 220)
            again, new2 = fm.fetch_imagery(self.CFG, data, d, fetch=lambda u: 1 / 0, today=date(2026, 11, 15))
            self.assertFalse(new2)
            self.assertIs(again, data)


if __name__ == "__main__":
    unittest.main()
