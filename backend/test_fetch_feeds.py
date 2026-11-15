"""Fixture tests for the feed parsers. Run: python -m unittest backend/test_fetch_feeds.py"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import fetch_feeds as ff  # noqa: E402

USGS = json.dumps({"type": "FeatureCollection", "metadata": {"url": "https://earthquake.usgs.gov/x"}, "features": [
    {"type": "Feature", "id": "us7000abcd", "geometry": {"type": "Point", "coordinates": [142.1, 38.2, 10]},
     "properties": {"mag": 5.4, "magType": "mww", "place": "off the east coast of Honshu", "time": 1763190000000,
                    "title": "M 5.4 - off the east coast of Honshu, Japan", "type": "earthquake", "url": "https://u", "alert": "green"}},
    {"type": "Feature", "id": "bad", "geometry": None, "properties": {}}]}).encode()

EONET = json.dumps({"events": [
    {"id": "EONET_1", "title": "Wildfire X", "link": "https://l", "categories": [{"id": "wildfires", "title": "Wildfires"}],
     "sources": [{"url": "https://s"}], "geometry": [
        {"date": "2026-11-10T00:00:00Z", "type": "Point", "coordinates": [-120.0, 38.0]},
        {"date": "2026-11-12T00:00:00Z", "type": "Point", "coordinates": [-121.0, 39.0], "magnitudeValue": 1200, "magnitudeUnit": "acres"}]},
    {"id": "EONET_2", "title": "Ice", "categories": [{"title": "Sea and Lake Ice"}], "geometry": [
        {"date": "2026-11-11T00:00:00Z", "type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2]]]}]},
    {"id": "EONET_3", "title": "No geometry", "categories": [], "geometry": []}]}).encode()

NWS = json.dumps({"type": "FeatureCollection", "features": [
    {"id": "https://api.weather.gov/alerts/1", "geometry": {"type": "Polygon", "coordinates": [[[-100, 40], [-98, 40], [-98, 42], [-100, 42], [-100, 40]]]},
     "properties": {"id": "urn:1", "event": "Winter Storm Warning", "headline": "Winter Storm Warning issued", "sent": "2026-11-15T10:00:00-05:00", "severity": "Severe", "@id": "https://api.weather.gov/alerts/1"}},
    {"id": "z", "geometry": None, "properties": {"event": "Zone only"}}]}).encode()

FIRMS = ("latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"
         "-10.5,25.1,340.1,0.4,0.4,2026-11-15,0130,N,VIIRS,h,2.0NRT,290,55.2,N\n"
         "-11.5,26.1,330.1,0.4,0.4,2026-11-15,0945,N,VIIRS,n,2.0NRT,290,99.0,D\n"
         "12.0,100.0,345.0,0.4,0.4,2026-11-14,2359,N,VIIRS,h,2.0NRT,290,12.0,N\n").encode()


class Parsers(unittest.TestCase):
    def test_usgs(self):
        e = ff.parse_usgs(USGS)
        self.assertEqual(len(e), 1)
        self.assertEqual(e[0]["mag"], 5.4)
        self.assertEqual(e[0]["src"], "USGS")
        self.assertEqual((e[0]["lon"], e[0]["lat"]), (142.1, 38.2))

    def test_eonet_uses_latest_position(self):
        e = ff.parse_eonet(EONET)
        self.assertEqual(len(e), 2)
        self.assertEqual((e[0]["lon"], e[0]["lat"]), (-121.0, 39.0))
        self.assertEqual(e[0]["mag"], 1200)
        self.assertEqual(e[0]["t"], ff.iso_ms("2026-11-12T00:00:00Z"))
        self.assertEqual(e[1]["cat"], "Sea and Lake Ice")

    def test_nws_skips_zone_only(self):
        e = ff.parse_nws(NWS)
        self.assertEqual(len(e), 1)
        self.assertEqual(e[0]["severity"], "Severe")
        self.assertEqual(e[0]["t"], ff.iso_ms("2026-11-15T15:00:00Z"))

    def test_firms_high_confidence_sorted(self):
        e = ff.parse_firms(FIRMS)
        self.assertEqual([x["mag"] for x in e], [55.2, 12.0])
        self.assertEqual(e[0]["t"], ff.iso_ms("2026-11-15T01:30:00Z"))

    def test_failed_source_keeps_previous(self):
        previous = {"events": [{"id": "NASA FIRMS-old", "src": "NASA FIRMS", "lon": 1, "lat": 1}],
                    "sources": [{"id": "firms", "fetched": "2026-11-15T10:00:00+00:00"}]}
        data = {"usgs": USGS, "eonet": EONET, "nws": NWS}

        def fake(url):
            for k, v in data.items():
                if url == ff.SOURCES[k]["url"]:
                    return v
            raise TimeoutError("simulated outage")

        out = ff.build(previous, fetch=fake)
        firms = next(s for s in out["sources"] if s["id"] == "firms")
        self.assertTrue(firms["stale"])
        self.assertFalse(firms["ok"])
        self.assertEqual(firms["count"], 1)
        self.assertEqual(firms["fetched"], "2026-11-15T10:00:00+00:00")
        self.assertIn("NASA FIRMS-old", [e["id"] for e in out["events"]])
        self.assertEqual(len(out["events"]), 1 + 2 + 1 + 1)


if __name__ == "__main__":
    unittest.main()
