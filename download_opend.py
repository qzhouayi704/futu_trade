import urllib.request, re, os
print("Fetching download link...")
try:
    req = urllib.request.Request("https://www.futunn.com/download/OpenAPI", headers={'User-Agent': 'Mozilla/5.0'})
    html = urllib.request.urlopen(req).read().decode("utf-8")
    match = re.search(r"https://[^\"]*FutuOpenD[^\"]*Ubuntu[^\"]*\.tar\.gz", html)
    if not match:
        # Fallback to standard URL format if scraping fails
        url = "https://softwaredownload.futunn.com/FutuOpenD_8.5.3408_Ubuntu16.04.tar.gz" # Try fallback if needed, but regex should work
        print("Regex failed to find Ubuntu tar.gz")
    else:
        url = match.group(0)
    print(f"Found URL: {url}")
    os.system(f"mkdir -p /opt/FutuOpenD && cd /opt/FutuOpenD && wget -qO opend.tar.gz {url} && tar -xzf opend.tar.gz --strip-components=1 && chmod +x FutuOpenD")
    print("Install success!")
except Exception as e:
    print(f"Error: {e}")
