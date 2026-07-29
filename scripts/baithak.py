import requests
import re
import time
from PIL import Image, ImageFile
from io import BytesIO
from datetime import datetime
import os

ImageFile.LOAD_TRUNCATED_IMAGES = True

today = datetime.now()
DATE = today.strftime("%Y-%m-%d")
DAY = today.strftime("%d")
MONTH_SHORT = today.strftime("%b")

# ===== EDITIONS (city name -> slug used by epaper.baithak.news) =====
editions = {
    "Multan": "multan",
    "Loralai": "loralai",
    "Rahim Yar Khan": "rhym-yar-khan",   # site's own spelling, confirmed from their dropdown
}

BASE = "https://epaper.baithak.news/{slug}/{date}/{page}"
MAX_PAGES = 24
MAX_RETRIES = 3
PAGE_DELAY = 0.6

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"),
}

OGIMAGE_PATTERN = re.compile(
    r'property="og:image"\s+content="([^"]+\.(?:jpg|jpeg|png))"',
    re.IGNORECASE
)

SAVE_FOLDER = "Baithak_PDFs"
os.makedirs(SAVE_FOLDER, exist_ok=True)


def get_full_res_url(thumb_url):
    """og:image usually ends in _thumb.jpg — try the non-thumb version first."""
    if "_thumb" in thumb_url:
        return thumb_url.replace("_thumb", "")
    return thumb_url


def download_edition(edition, slug, debug_dump=False):
    print(f"\n📖 Downloading {edition} newspaper...")
    session = requests.Session()
    images = []

    for page in range(1, MAX_PAGES + 1):
        url = BASE.format(slug=slug, date=DATE, page=page)
        r = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                r = session.get(url, headers=HEADERS, timeout=20)
                if r.status_code == 200:
                    break
            except Exception as e:
                time.sleep(1.0 * attempt)

        if r is None or r.status_code != 200:
            print(f"  ℹ️  {edition} page {page}: HTTP {r.status_code if r else 'no response'} — stopping here.")
            break

        match = OGIMAGE_PATTERN.search(r.text)
        if not match:
            print(f"  ℹ️  {edition} page {page}: no og:image tag — assuming last page.")
            if debug_dump and page == 1:
                dump_path = os.path.join(SAVE_FOLDER, f"debug_{edition}.html")
                with open(dump_path, "w", encoding="utf-8") as f:
                    f.write(r.text)
                print(f"  ⚠️  Page 1 itself had no image — HTML saved to {dump_path}")
            break

        thumb_url = match.group(1)
        full_url = get_full_res_url(thumb_url)

        img = None
        for candidate in (full_url, thumb_url):
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    ir = session.get(candidate, headers=HEADERS, timeout=15)
                    if ir.status_code == 200:
                        img = Image.open(BytesIO(ir.content)).convert("RGB")
                        break
                except Exception:
                    time.sleep(1.0 * attempt)
            if img is not None:
                break

        if img is None:
            print(f"  ({edition} page {page} image download failed)")
            break

        images.append(img)
        print(f"{edition} - Page {page} added")
        time.sleep(PAGE_DELAY)

    if images:
        pdf_name = f"Baithak {edition} {DAY}{MONTH_SHORT}.pdf"
        pdf_path = os.path.join(SAVE_FOLDER, pdf_name)
        images[0].save(pdf_path, save_all=True, append_images=images[1:])
        print(f"✅ {edition} PDF ready: {pdf_path}  ({len(images)} pages)")
    else:
        print(f"❌ {edition} pages not found")


for edition, slug in editions.items():
    download_edition(edition, slug, debug_dump=True)
    time.sleep(1.5)
