import re
import sys
import os
import time
from io import BytesIO
from datetime import datetime
from urllib.parse import quote

import requests
from PIL import Image

try:
    from curl_cffi import requests as cf_requests
except ImportError:
    cf_requests = None


MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 13; Mobile) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Mobile Safari/537.36"
)
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": DESKTOP_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://e.asas.pk/",
}

# City codes used by asas.pk
CITIES = {
    "isb": "Islamabad/Rawalpindi",
    "khi": "Karachi",
    "lhr": "Lahore",
    "fsd": "Faisalabad",
}


def make_session():
    if cf_requests:
        try:
            s = cf_requests.Session(impersonate="chrome124")
            s.headers.update(HEADERS)
            return s
        except Exception:
            pass
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


SESSION = make_session()


def safe_get(url, tries=3):
    for i in range(tries):
        try:
            r = SESSION.get(url, timeout=30)
            if r.status_code == 200:
                return r
            print(f"HTTP {r.status_code}, retry {i+1}/{tries}")
        except Exception as e:
            print("Connection error:", e)
        time.sleep(2)
    return None


def get_today_date_str():
    today = datetime.now()
    return f"{today.day:02d}-{today.month:02d}-{today.year}"


def get_page_images(date_str, city):
    """Page 1 se hi saari pages ki image URLs mil jaati hain (thumbnail grid)."""
    listing_url = f"https://e.asas.pk/page.php?Page=1&date={date_str}&city={city}"
    print(f"[{city}] Fetching:", listing_url)

    r = safe_get(listing_url)
    if not r:
        raise RuntimeError(
            f"[{city}] Listing page open nahi hui. Internet ya website block check karein."
        )

    html = r.text

    # Filename prefix varies by city: isb="01", khi="01 k", lhr/fsd="p1" etc.
    # so capture everything up to a "-<10-digit-timestamp>.<ext>" suffix.
    matches = re.findall(r'uploads/([^"/]+?)-(\d{10})\.(jpg|jpeg|png)', html, re.IGNORECASE)

    if not matches:
        # Debug ke liye asal HTML save kardo taake pata chale server ne kya bheja
        os.makedirs("debug", exist_ok=True)
        debug_path = f"debug/{city}_{date_str}.html"
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"⚠️ [{city}] HTML mein images nahi milin. Raw response yahan save hui: {debug_path}")
        print(f"[{city}] Response length: {len(html)} chars. Pehle 300 chars:\n{html[:300]}\n")
        raise RuntimeError(
            f"[{city}] Is date ke liye pages nahi milin. Date available nahi ho sakti."
        )

    seen = {}
    for prefix, ts, ext in matches:
        if prefix not in seen:
            encoded_name = quote(f"{prefix}-{ts}.{ext}")
            seen[prefix] = f"https://e.asas.pk/uploads/{encoded_name}"

    def page_sort_key(prefix):
        m = re.search(r'\d+', prefix)
        return int(m.group()) if m else 0

    ordered = [seen[k] for k in sorted(seen.keys(), key=page_sort_key)]
    return ordered


def download_city_epaper(date_str, city):
    print(f"\n===== {CITIES.get(city, city)} ({city}) =====")

    img_urls = get_page_images(date_str, city)
    print(f"📄 [{city}] Total {len(img_urls)} pages mili")

    pdf_images = []
    out_dir = f"asas_pages/{city}_{date_str}"
    os.makedirs(out_dir, exist_ok=True)

    for idx, img_url in enumerate(img_urls, start=1):
        print(f"[{city}] Downloading page {idx}:", img_url)
        r = safe_get(img_url)

        if r:
            try:
                img = Image.open(BytesIO(r.content)).convert("RGB")
                pdf_images.append(img)
                img.save(f"{out_dir}/{idx:02d}.jpg")
                print(f"✅ [{city}] Page {idx} saved")
            except Exception as e:
                print(f"❌ [{city}] Image error page {idx}: {e}")
        else:
            print(f"❌ [{city}] Page {idx} download failed")

    if pdf_images:
        os.makedirs("asas_pdfs", exist_ok=True)
        pdf_path = f"asas_pdfs/Asas_{city}_{date_str}.pdf"
        pdf_images[0].save(pdf_path, save_all=True, append_images=pdf_images[1:])
        print(f"📕 [{city}] PDF ready:", pdf_path)
        return pdf_path
    else:
        print(f"⚠️ [{city}] Koi page download nahi hui.")
        return None


def download_all_editions(date_str=None, cities=None):
    if date_str is None:
        date_str = get_today_date_str()
    if cities is None:
        cities = list(CITIES.keys())  # isb, khi, lhr, fsd

    results = {}
    for city in cities:
        try:
            results[city] = download_city_epaper(date_str, city)
        except Exception as e:
            print(f"❌ [{city}] Failed:", e)
            results[city] = None

    print("\n===== Summary =====")
    for city, path in results.items():
        status = path if path else "FAILED"
        print(f"{city}: {status}")


if __name__ == "__main__":
    # Usage:
    #   python asas_epaper.py                     -> aaj ki date, sab 4 editions
    #   python asas_epaper.py 25-07-2026           -> specific date, sab 4 editions
    #   python asas_epaper.py 25-07-2026 lhr,khi   -> specific date, sirf chosen cities
    date_arg = None
    city_arg = None

    if len(sys.argv) > 1:
        m = re.search(r'(\d{2}-\d{2}-\d{4})', sys.argv[1])
        date_arg = m.group(1) if m else None

    if len(sys.argv) > 2:
        city_arg = [c.strip().lower() for c in sys.argv[2].split(",")]

    download_all_editions(date_arg, city_arg)
