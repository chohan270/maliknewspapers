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
DATE = today.strftime("%Y-%m-%d")   # e.g. 2026-07-07
DAY = today.strftime("%d")
MONTH_SHORT = today.strftime("%b")

# ===== EDITIONS (city name -> url slug used by nawaiwaqt.com.pk) =====
# Only these 6 editions kept, rest removed on request.
editions = {
    "Lahore": "lahore",
    "Islamabad": "islamabad",
    "Karachi": "karachi",
    "Multan": "multan",
    "Quetta": "Quetta",
    "Gawadar": "Gawadar",
}

# Sunday Magazine has its own slug and its own page numbering on the site.
# Kept as a SEPARATE dict/edition so it downloads into its own PDF instead
# of getting appended onto Lahore's pages.
sunday_magazine = {
    "Sunday Magazine": "sunday-magazine",
}

BASE = "https://www.nawaiwaqt.com.pk/E-Paper"
MAX_PAGES = 24
MAX_RETRIES = 3          # for genuine network errors
MISMATCH_RETRIES = 5     # for "got the wrong city's image back" (be patient, this is a site-side hiccup, not a missing page)
PAGE_DELAY = 0.8         # slowed back down — 0.15 was triggering the site's rate-limiting / anti-bot response
EDITION_DELAY = 2.0      # pause between editions so we don't hammer the site right after finishing one

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"),
    "Connection": "close",
    "Cache-Control": "no-cache",
}

IMG_PATTERN = re.compile(
    r'property="og:image"\s+content="(https://www\.nawaiwaqt\.com\.pk/epaper_image/[^"]+\.(?:jpg|jpeg|png|gif|webp))"',
    re.IGNORECASE
)

SAVE_FOLDER = "Nawaiwaqt_PDFs"
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
                # THIS WAS THE BUG: a single request with no og:image tag used
                # to be treated as "definitely the last page" with zero retry.
                # But a transient glitch (anti-bot page, partial response,
                # temporary server hiccup) also looks like "no match" for one
                # request — it does NOT mean the edition has ended. So retry
                # a few times first, same as we do for mismatches.
                no_match_count += 1
                print(f"  ⚠️  {city_slug} page {page_num}: no image tag found on this attempt "
                      f"({attempt}/{MISMATCH_RETRIES}), retrying before giving up...")
                time.sleep(1.5 * attempt)  # restored — 0.6 was too aggressive
                continue

            img_url = match.group(1)

            if city_slug.lower() not in img_url.lower():
                last_mismatch_city = img_url.split('/')[-2]
                print(f"  ⚠️  {city_slug} page {page_num}: got {last_mismatch_city}'s image instead "
                      f"(attempt {attempt}/{MISMATCH_RETRIES}), retrying...")
                time.sleep(1.5 * attempt)  # restored — 0.6 was too aggressive
                continue

            return PageResult("ok", img_url=img_url)

        except Exception as e:
            if attempt == MAX_RETRIES:
                return PageResult("error", detail=str(e))
            time.sleep(2.0 * attempt)  # restored — 0.8 was too aggressive

    # Only after several consistent retries do we conclude the edition
    # has genuinely ended (or that the mismatch could never be resolved).
    if no_match_count >= MISMATCH_RETRIES:
        return PageResult("not_found", detail=f"no og:image tag after {MISMATCH_RETRIES} tries (genuinely last page)")

    return PageResult(
        "mismatch_unresolved",
        detail=f"kept getting {last_mismatch_city}'s image instead of {city_slug} after {MISMATCH_RETRIES} tries"
    )


def download_edition(edition, city_slug):
    print(f"\n📖 Downloading {edition} newspaper...")
    images = []
    session = requests.Session()

    for page in range(1, MAX_PAGES + 1):
        result = get_page_image_url(city_slug, page, session)

        if result.status == "not_found":
            # genuine end of the edition — stop paging here
            print(f"  ℹ️  {edition} page {page}: {result.detail} — stopping here.")
            break

        if result.status in ("error", "mismatch_unresolved"):
            # NOT necessarily the end of the edition — could just be a
            # temporary site hiccup on this one page. Report it clearly
            # instead of silently stopping, so it's obvious what happened.
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
                    time.sleep(2.0 * attempt)  # restored — 0.8 was too aggressive

        if img is None:
            break
        images.append(img)
        print(f"{edition} - Page {page} added")
        time.sleep(PAGE_DELAY)

    if images:
        pdf_name = f"Nawaiwaqt {edition} {DAY}{MONTH_SHORT}.pdf"
        pdf_path = os.path.join(SAVE_FOLDER, pdf_name)
        images[0].save(pdf_path, save_all=True, append_images=images[1:])
        print(f"✅ {edition} PDF ready: {pdf_path}  ({len(images)} pages)")
    else:
        print(f"❌ {edition} pages not found")


# ===== Run all editions, ONE AT A TIME =====
# Fully sequential now — next edition only starts after the current one
# is completely done. No overlap, no concurrency-related mix-ups.
for edition, city_slug in editions.items():
    download_edition(edition, city_slug)
    time.sleep(EDITION_DELAY)

# ===== Sunday Magazine — always its own separate PDF =====
# Runs as its own pass, after all city editions, using its own slug/page
# numbering, so it never gets mixed into Lahore's (or any other edition's) PDF.
for edition, city_slug in sunday_magazine.items():
    download_edition(edition, city_slug)
    time.sleep(EDITION_DELAY)
