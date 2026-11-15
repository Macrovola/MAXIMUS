import urllib.request, sys, datetime
UA={"User-Agent":"MAXIMUS-GEOINT-Tracker/1.0 (github.com/Macrovola/MAXIMUS)"}
y=(datetime.datetime.utcnow()-datetime.timedelta(days=1)).strftime("%Y-%m-%d")
gibs="https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?SERVICE=WMS&REQUEST=GetMap&VERSION=1.1.1&LAYERS={L}&SRS=EPSG:4326&BBOX=20,40,60,62&WIDTH=800&HEIGHT=440&FORMAT=image/jpeg&TIME="+y
urls=[
"http://data.gdeltproject.org/gdeltv2/lastupdate.txt",
"https://api.gdeltproject.org/api/v2/geo/geo?query=protest&format=GeoJSON&timespan=24h",
gibs.replace("{L}","VIIRS_NOAA20_CorrectedReflectance_TrueColor"),
gibs.replace("{L}","VIIRS_SNPP_CorrectedReflectance_TrueColor"),
gibs.replace("{L}","MODIS_Terra_CorrectedReflectance_TrueColor"),
"https://www.gdacs.org/xml/rss.xml",
"https://reliefweb.int/updates/rss.xml",
"https://feeds.bbci.co.uk/news/world/rss.xml",
"https://feeds.bbci.co.uk/news/world/europe/rss.xml",
"https://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
"https://feeds.bbci.co.uk/news/world/asia/rss.xml",
"https://feeds.bbci.co.uk/news/world/africa/rss.xml",
"https://feeds.bbci.co.uk/news/world/latin_america/rss.xml",
"https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml",
"https://www.aljazeera.com/xml/rss/all.xml",
"https://news.un.org/feed/subscribe/en/news/all/rss.xml",
"https://feeds.npr.org/1004/rss.xml",
"https://kyivindependent.com/news-archive/rss/",
"https://meduza.io/rss/en/all",
"https://www.rferl.org/api/",
"https://www.themoscowtimes.com/rss/news",
"https://www.france24.com/en/rss",
"https://rss.dw.com/rdf/rss-en-all",
"https://www.thearcticinstitute.org/feed/",
"https://www.highnorthnews.com/en/rss.xml",
"https://www.scmp.com/rss/91/feed",
"https://www3.nhk.or.jp/nhkworld/en/news/feeds/",
"https://www.africanews.com/feed/rss",
"https://www.timesofisrael.com/feed/",
"https://www.youtube.com/@aljazeeraenglish/live",
"https://www.youtube.com/@dwnews/live",
"https://www.youtube.com/@France24_en/live",
"https://www.youtube.com/@SkyNews/live",
"https://www.youtube.com/@NASA/live",
"https://www.usgs.gov/volcanoes/kilauea/webcams",
"https://www.usgs.gov/volcanoes/mount-st-helens/webcams",
"https://avo.alaska.edu/webcam/",
"https://www.youtube.com/@ABCNewsAustralia/live",
"https://www.youtube.com/@WION/live",
"https://www.youtube.com/@CNA/live",
"https://www.youtube.com/@NHKWORLDJAPAN/live",
"https://www.youtube.com/@Bloomberg/live",
"https://www.youtube.com/@euronews/live",
"https://www.youtube.com/@KyivIndependent/live",
"https://www.youtube.com/@ArirangNews/live",
"https://www.youtube.com/@TRTWorld/live",
"https://www.youtube.com/@CBSNews/live",
"https://www.youtube.com/@NBCNews/live",
]
for u in urls:
    try:
        r=urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=40); b=r.read(400000)
        head=b[:160].decode("utf-8","replace").replace("\n"," ")
        extra=""
        if "youtube" in u: extra=" LIVE" if b'"isLive":true' in b or b'isLiveNow' in b or b'"style":"LIVE"' in b else " notlive?"
        print(f"{r.status} {r.headers.get('Content-Type','')[:30]:30} {len(b):>7} {u[:95]}{extra} | {head[:90]}")
    except Exception as e:
        print(f"ERR {type(e).__name__}: {str(e)[:60]} {u[:95]}")
# gdelt export sample
try:
    lu=urllib.request.urlopen(urllib.request.Request(urls[0],headers=UA),timeout=40).read().decode()
    print(lu)
    exp=[l.split()[2] for l in lu.splitlines() if l.endswith("export.CSV.zip")][0]
    import zipfile,io
    z=zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(urllib.request.Request(exp,headers=UA),timeout=60).read()))
    data=z.read(z.namelist()[0]).decode("utf-8","replace").splitlines()
    print("rows",len(data),"cols",len(data[0].split("\t")))
    for l in data[:2]: print(l.split("\t"))
except Exception as e: print("GDELT export ERR",e)
