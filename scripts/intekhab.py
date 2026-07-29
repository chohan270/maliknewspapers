import requests
import re
import time
from PIL import Image, ImageFile
from io import BytesIO
from datetime import datetime
import os

ImageFile.LOAD_TRUNCATED_IMAGES = True

# ===== TODAY DATE (site uses MM-DD-YY) =====
today = datetime.now()
DATE = today.strftime("%m-%d-%y")
DAY = today.strftime("%d")
MONTH_SHORT = today.strftime("%b")

# ===== EDITIONS (city name -> edition id used by dailyintekhab) =====
editions = {
    "Hub": 1,
    "Quetta": 2,
    "Karachi": 3,
}

BASE = "https://epaper.dailyintekhab.pk/today/st/{eid}/1/{date}"
MAX_RETRIES = 3
PAGE_DELAY = 0.5

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"),
}

# Har page ki thumbnail is single request me hi mil jaati hai (poori list),
# is liye har page ke liye alag request karne ki zarurat nahi.
IMG_PATTERN = re.compile(
    r'(https://epaper\.dailyintekhab\.pk/uploads/[^"\'\)\s]+?page-(\d+)\.jpg)',
    re.IGNORECASE
)

SAVE_FOLDER = "DailyIntekhab_PDFs"
os.makedirs(SAVE_FOLDER, exist_ok=True)


def download_edition(edition, eid, debug_dump=False):
    print(f"\n📖 Downloading {edition} newspaper...")
    session = requests.Session()
    url = BASE.format(eid=eid, date=DATE)

    r = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                break
        except Exception as e:
            print(f"  ⚠️  attempt {attempt} failed: {e}")
        time.sleep(1.0 * attempt)

    if r is None or r.status_code != 200:
        print(f"  ❌ {edition}: could not load page listing (HTTP {r.status_code if r else 'no response'})")
        return

    matches = IMG_PATTERN.findall(r.text)
    if not matches:
        print(f"  ❌ {edition}: no page images found on listing page.")
        if debug_dump:
            dump_path = os.path.join(SAVE_FOLDER, f"debug_{edition}.html")
            with open(dump_path, "w", encoding="utf-8") as f:
                f.write(r.text)
            print(f"  ℹ️  Raw HTML saved to {dump_path} for inspection.")
        return

    # dedupe + sort by page number, keep url
    page_map = {}
    for img_url, page_num in matches:
        page_map[int(page_num)] = img_url
    sorted_pages = sorted(page_map.items())

    images = []
    for page_num, img_url in sorted_pages:
        img = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                ir = session.get(img_url, headers=HEADERS, timeout=15)
                img = Image.open(BytesIO(ir.content)).convert("RGB")
                break
            except Exception as e:
                if attempt == MAX_RETRIES:
                    print(f"  ({edition} page {page_num} image download failed after {MAX_RETRIES} tries: {e})")
                else:
                    time.sleep(1.0 * attempt)
        if img is None:
            continue
        images.append(img)
        print(f"{edition} - Page {page_num} added")
        time.sleep(PAGE_DELAY)

    if images:
        pdf_name = f"Intekhab {edition} {DAY}{MONTH_SHORT}.pdf"
        pdf_path = os.path.join(SAVE_FOLDER, pdf_name)
        images[0].save(pdf_path, save_all=True, append_images=images[1:])
        print(f"✅ {edition} PDF ready: {pdf_path}  ({len(images)} pages)")
    else:
        print(f"❌ {edition} pages not found")


for edition, eid in editions.items():
    download_edition(edition, eid, debug_dump=True)
    time.sleep(1.5)
