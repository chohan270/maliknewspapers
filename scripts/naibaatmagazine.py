import requests
import re
import time
from PIL import Image
from io import BytesIO
from datetime import datetime
import os

# ===== TODAY DATE (YYYY-MM-DD) =====
today = datetime.now()
DATE = today.strftime("%Y-%m-%d")   # e.g. 2026-07-07
DAY = today.strftime("%d")
MONTH_SHORT = today.strftime("%b")

# ===== EDITIONS (city name -> url slug) =====
# Sirf Sunday Magazine
editions = {
    "Sunday Magazine": "sunday-magazine",
}

BASE = "https://www.naibaat.pk/E-Paper"
MAX_PAGES = 30
MAX_RETRIES = 3
MISMATCH_RETRIES = 5
PAGE_DELAY = 0.15        # ⚡ OPTIMIZED: reduced from 0.6 for faster downloads

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"),
    "Connection": "close",
    "Cache-Control": "no-cache",
}

# Same as Nawaiwaqt — og:image tag with jpg/jpeg/png, case-insensitive
IMG_PATTERN = re.compile(
    r'property="og:image"\s+content="(https://www\.naibaat\.pk/epaper_image/[^"]+\.(?:jpg|jpeg|png))"',
    re.IGNORECASE
)

SAVE_FOLDER = "NaiBaat_PDFs"
os.makedirs(SAVE_FOLDER, exist_ok=True)


class PageResult:
    def __init__(self, status, img_url=None, detail=""):
        self.status = status
        self.img_url = img_url
        self.detail = detail


def get_page_image_url(city_slug, page_num, session):
    url = f"{BASE}/{city_slug}/{DATE}/page-{page_num}?_={int(time.time() * 1000)}"
    last_mismatch_city = None
    no_match_count = 0

    for attempt in range(1, MISMATCH_RETRIES + 1):
        try:
            r = session.get(url, headers=HEADERS, timeout=15)

            if r.status_code != 200:
                return PageResult("not_found", detail=f"HTTP {r.status_code}")

            match = IMG_PATTERN.search(r.text)
            if not match:
                no_match_count += 1
                print(f"  ⚠️  {city_slug} page {page_num}: no image tag found on this attempt "
                      f"({attempt}/{MISMATCH_RETRIES}), retrying before giving up...")
                time.sleep(0.6 * attempt)  # ⚡ OPTIMIZED: reduced from 1.5 * attempt
                continue

            img_url = match.group(1)

            if city_slug.lower() not in img_url.lower():
                last_mismatch_city = img_url.split('/')[-2]
                print(f"  ⚠️  {city_slug} page {page_num}: got {last_mismatch_city}'s image instead "
                      f"(attempt {attempt}/{MISMATCH_RETRIES}), retrying...")
                time.sleep(0.6 * attempt)  # ⚡ OPTIMIZED: reduced from 1.5 * attempt
                continue

            return PageResult("ok", img_url=img_url)

        except Exception as e:
            if attempt == MAX_RETRIES:
                return PageResult("error", detail=str(e))
            time.sleep(0.8 * attempt)  # ⚡ OPTIMIZED: reduced from 2 * attempt

    if no_match_count >= MISMATCH_RETRIES:
        return PageResult("not_found", detail=f"no og:image tag after {MISMATCH_RETRIES} tries (genuinely last page)")

    return PageResult(
        "mismatch_unresolved",
        detail=f"kept getting {last_mismatch_city}'s image instead of {city_slug} after {MISMATCH_RETRIES} tries"
    )


def download_edition(edition, city_slug):
    print(f"\n📰 Downloading {edition} newspaper...")
    images = []
    session = requests.Session()

    for page in range(1, MAX_PAGES + 1):
        result = get_page_image_url(city_slug, page, session)

        if result.status == "not_found":
            print(f"  ℹ️  {edition} page {page}: {result.detail} — stopping here.")
            break

        if result.status in ("error", "mismatch_unresolved"):
            print(f"  ❌ {edition} page {page}: stopped here — {result.detail}. "
                  f"Re-run the script if you think {edition} actually has more pages.")
            break

        img_url = result.img_url
        img = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                r = session.get(img_url, headers=HEADERS, timeout=15)
                img = Image.open(BytesIO(r.content)).convert("RGB")
                break
            except Exception as e:
                if attempt == MAX_RETRIES:
                    print(f"  ({edition} page {page} image download failed after {MAX_RETRIES} tries: {e})")
                else:
                    time.sleep(0.8 * attempt)  # ⚡ OPTIMIZED: reduced from 2 * attempt

        if img is None:
            break
        images.append(img)
        print(f"{edition} - Page {page} added")
        time.sleep(PAGE_DELAY)

    if images:
        pdf_name = f"NaiBaat {edition} {DAY}{MONTH_SHORT}.pdf"
        pdf_path = os.path.join(SAVE_FOLDER, pdf_name)
        images[0].save(pdf_path, save_all=True, append_images=images[1:])
        print(f"✅ {edition} PDF ready: {pdf_path}  ({len(images)} pages)")
    else:
        print(f"❌ {edition} pages not found")


# ===== Run all editions, ONE AT A TIME =====
for edition, city_slug in editions.items():
    download_edition(edition, city_slug)
