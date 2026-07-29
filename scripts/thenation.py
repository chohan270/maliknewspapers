import requests
import re
import time
from PIL import Image, ImageFile
from io import BytesIO
from datetime import datetime
import os

ImageFile.LOAD_TRUNCATED_IMAGES = True  # tolerate slightly incomplete responses instead of hard-failing

# ===== TODAY DATE (YYYY-MM-DD) =====
today = datetime.now()
DATE = today.strftime("%Y-%m-%d")   # e.g. 2026-07-12
DAY = today.strftime("%d")
MONTH_SHORT = today.strftime("%b")

# ===== EDITIONS (city name -> url slug used by nation.com.pk) =====
# The Nation same Nawaiwaqt Group hi chalata hai, isi liye site ka pattern
# bilkul nawaiwaqt.com.pk jaisa hai. Site per 5 editions hain
# (Lahore, Islamabad, Karachi, Quetta, Gwadar) — sirf 3 main editions
# (Lahore, Karachi, Islamabad) rakhe hain jaisa aap ne bola. Neeche
# comment se Quetta/Gwadar bhi add kar sakte hain agar chahiye.
editions = {
    "Lahore": "lahore",
    "Karachi": "karachi",
    "Islamabad": "islamabad",
    # "Quetta": "quetta",
    # "Gwadar": "gwadar",
}

BASE = "https://www.nation.com.pk/E-Paper"
MAX_PAGES = 20
MAX_RETRIES = 3          # for genuine network errors
MISMATCH_RETRIES = 5     # for "got the wrong city's image back" (site-side hiccup, not a missing page)
PAGE_DELAY = 0.8
EDITION_DELAY = 2.0      # pause between editions so we don't hammer the site right after finishing one

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"),
    "Connection": "close",
    "Cache-Control": "no-cache",
}

IMG_PATTERN = re.compile(
    r'property="og:image"\s+content="(https://www\.nation\.com\.pk/epaper_image/[^"]+\.(?:jpg|jpeg|png|gif|webp))"',
    re.IGNORECASE
)

SAVE_FOLDER = "TheNation_PDFs"
os.makedirs(SAVE_FOLDER, exist_ok=True)


class PageResult:
    """Return type for get_page_image_url so we can tell WHY paging stopped."""
    def __init__(self, status, img_url=None, detail=""):
        self.status = status      # "ok" | "not_found" | "mismatch_unresolved" | "error"
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
                time.sleep(1.5 * attempt)
                continue

            img_url = match.group(1)

            if city_slug.lower() not in img_url.lower():
                last_mismatch_city = img_url.split('/')[-2]
                print(f"  ⚠️  {city_slug} page {page_num}: got {last_mismatch_city}'s image instead "
                      f"(attempt {attempt}/{MISMATCH_RETRIES}), retrying...")
                time.sleep(1.5 * attempt)
                continue

            return PageResult("ok", img_url=img_url)

        except Exception as e:
            if attempt == MAX_RETRIES:
                return PageResult("error", detail=str(e))
            time.sleep(2.0 * attempt)

    if no_match_count >= MISMATCH_RETRIES:
        return PageResult("not_found", detail=f"no og:image tag after {MISMATCH_RETRIES} tries (genuinely last page)")

    return PageResult(
        "mismatch_unresolved",
        detail=f"kept getting {last_mismatch_city}'s image instead of {city_slug} after {MISMATCH_RETRIES} tries"
    )


def download_edition(edition, city_slug):
    print(f"\n📖 Downloading The Nation {edition} edition...")
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
                    time.sleep(2.0 * attempt)

        if img is None:
            break
        images.append(img)
        print(f"{edition} - Page {page} added")
        time.sleep(PAGE_DELAY)

    if images:
        pdf_name = f"TheNation {edition} {DAY}{MONTH_SHORT}.pdf"
        pdf_path = os.path.join(SAVE_FOLDER, pdf_name)
        images[0].save(pdf_path, save_all=True, append_images=images[1:])
        print(f"✅ {edition} PDF ready: {pdf_path}  ({len(images)} pages)")
    else:
        print(f"❌ {edition} pages not found")


# ===== Run all editions, ONE AT A TIME =====
for edition, city_slug in editions.items():
    download_edition(edition, city_slug)
    time.sleep(EDITION_DELAY)
