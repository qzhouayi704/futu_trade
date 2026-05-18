import urllib.request
import re

url = "https://www.futunn.com/about/api-doc?lang=en"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
try:
    html = urllib.request.urlopen(req).read().decode('utf-8')
    links = re.findall(r'https://[^\s"\'<>]*FutuOpenD[^\s"\'<>]*Ubuntu[^\s"\'<>]*\.tar\.gz', html)
    print("Links found:", links)
except Exception as e:
    print("Error:", e)
