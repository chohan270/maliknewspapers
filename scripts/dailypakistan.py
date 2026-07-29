import requests
import re
import time
from PIL import Image, ImageFile
from io import BytesIO
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import os

ImageFile.LOAD_TRUNCATED_IMAGES = True

today = datetime.now()
DATE = today.strftime("%d-%m-%Y")   # site format: 23-07-2026
DAY = today.strftime("%d")
MONTH_FULL = today.strftime("%B")   # e.g. July

# ===== EDITIONS (English label -> Urdu slug used in the site's URL) =====
# Confirmed from the site's own edition dropdown.
editions = {
    "Islamabad": "اسلام آباد",
    "Rawalpindi": "راولپنڈی",
    "Karachi": "کراچی",
    "Karachi Action": "روزنامہ ایکشن کراچی",
    "Quetta": "کوئٹہ",
    "Karachi NayaRukh": "ماہنامہ نیا رخ کراچی",
    "Muzaffarabad": "مظفرآباد",
    "Multan": "ملتان",
    "MeraPakWatan": "میرا پاک وطن",
    "Nawabshah": "نوائے نواب شاہ",
}

# Custom PDF filename prefixes (per your naming convention). Editions not
# listed here default to "DailyPakistan {edition}".
PDF_NAME_PREFIX = {
    "Karachi Action": "Action Karachi",
    "Nawabshah": "Nawai NawabShah",
    "MeraPakWatan": "MeraPak Watan",
}

BASE = "https://dailypakistan.pk/epaper/editions/{date}-{slug}/"
MAX_RETRIES = 3
EDITION_DELAY = 0.4
IMG_WORKERS = 5

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"),
}

# Do tarah ki page images hoti hain:
# 1) "hotspot" widget wali pages (clickable/interactive) — alt text "P4-...",
#    "BP-..." — number seedha alt se milta hai (city ka naam kabhi galat hota
#    hai us alt me, lekin number sahi hota hai).
# 2) simple lazy-loaded pages jinke koi hotspot links nahi — id="myimage_4"
#    jaisa, real URL "data-src" me.
IMG_TAG_PATTERN = re.compile(r'<img[^>]+>', re.IGNORECASE)
ALT_PATTERN = re.compile(r'alt="([^"]*)"', re.IGNORECASE)
ID_PATTERN = re.compile(r'id="myimage_(\d+)"', re.IGNORECASE)
SRC_PATTERN = re.compile(
    r'(?:data-src|data-lazy-src|data-original|src)="([^"]+\.jpg)"',
    re.IGNORECASE
)
PAGE_NUM_ALT = re.compile(r'^P(\d+)\b', re.IGNORECASE)
FRONTPAGE_ALT = re.compile(r'^FP\b', re.IGNORECASE)
BACKPAGE_ALT = re.compile(r'^BP\b', re.IGNORECASE)
TOTAL_PAGES_PATTERN = re.compile(r'#page_(\d+)', re.IGNORECASE)

SAVE_FOLDER = "DailyPakistan_PDFs"
os.makedirs(SAVE_FOLDER, exist_ok=True)


def download_edition(edition, urdu_slug, debug_dump=False):
    print(f"\n📖 Downloading {edition} newspaper...")
    session = requests.Session()
    url = BASE.format(date=DATE, slug=urdu_slug.replace(" ", "-"))

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
        print(f"  ❌ {edition}: could not load edition page (HTTP {r.status_code if r else 'no response'})")
        return

    numbered_pages = {}   # page_num -> img_url
    backpage_url = None

    for tag in IMG_TAG_PATTERN.findall(r.text):
        src_match = SRC_PATTERN.search(tag)
        if not src_match:
            continue
        img_url = src_match.group(1)

        id_match = ID_PATTERN.search(tag)
        if id_match:
            numbered_pages[int(id_match.group(1))] = img_url
            continue

        alt_match = ALT_PATTERN.search(tag)
        if not alt_match:
            continue
        alt_text = alt_match.group(1).strip()

        page_num_match = PAGE_NUM_ALT.match(alt_text)
        if page_num_match:
            numbered_pages[int(page_num_match.group(1))] = img_url
            continue

        if FRONTPAGE_ALT.match(alt_text):
            if 1 not in numbered_pages:
                numbered_pages[1] = img_url
            continue

        if BACKPAGE_ALT.match(alt_text):
            backpage_url = img_url

    # figure out total page count from the site's own page-tab list, so we
    # know which number the back page ("BP") actually is
    tab_numbers = [int(n) for n in TOTAL_PAGES_PATTERN.findall(r.text)]
    total_pages = max(tab_numbers) if tab_numbers else None

    if backpage_url:
        if total_pages and total_pages not in numbered_pages:
            numbered_pages[total_pages] = backpage_url
        elif not total_pages:
            # fallback: no tab count found, just put it after the highest known page
            fallback_num = (max(numbered_pages) + 1) if numbered_pages else 1
            numbered_pages[fallback_num] = backpage_url

    real_pages_map = numbered_pages

    if not real_pages_map:
        print(f"  ❌ {edition}: no page images found on listing page.")
        dump_path = os.path.join(SAVE_FOLDER, f"debug_{edition}.html")
        with open(dump_path, "w", encoding="utf-8") as f:
            f.write(r.text)
        print(f"  ℹ️  Raw HTML saved to {dump_path}")
        return
    else:
        found_str = f"found {len(real_pages_map)} page(s)"
        if total_pages:
            found_str += f" out of {total_pages} available today"
        print(f"  ℹ️  {edition}: {found_str}.")
        if total_pages and len(real_pages_map) < total_pages:
            missing = sorted(set(range(1, total_pages + 1)) - set(real_pages_map))
            print(f"  ⚠️  {edition}: page(s) {missing} not on the site yet (or need a different pattern).")
            dump_path = os.path.join(SAVE_FOLDER, f"debug_{edition}.html")
            with open(dump_path, "w", encoding="utf-8") as f:
                f.write(r.text)
            print(f"  ℹ️  Raw HTML also saved to {dump_path} in case pattern needs adjusting.")

    sorted_pages = sorted(real_pages_map.items())

    def fetch_page(page_num, img_url):
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                ir = session.get(img_url, headers=HEADERS, timeout=15)
                img = Image.open(BytesIO(ir.content)).convert("RGB")
                return page_num, img
            except Exception as e:
                if attempt == MAX_RETRIES:
                    print(f"  ({edition} page {page_num} image download failed after {MAX_RETRIES} tries: {e})")
                else:
                    time.sleep(1.0 * attempt)
        return page_num, None

    results = {}
    with ThreadPoolExecutor(max_workers=IMG_WORKERS) as pool:
        futures = [pool.submit(fetch_page, pn, url) for pn, url in sorted_pages]
        for fut in as_completed(futures):
            page_num, img = fut.result()
            if img is not None:
                results[page_num] = img
                print(f"{edition} - Page {page_num} added")

    images = [results[pn] for pn, _ in sorted_pages if pn in results]

    if images:
        prefix = PDF_NAME_PREFIX.get(edition, f"Pakistan {edition}")
        pdf_name = f"{prefix} {DAY}{MONTH_FULL}.pdf"
        pdf_path = os.path.join(SAVE_FOLDER, pdf_name)
        images[0].save(pdf_path, save_all=True, append_images=images[1:])
        print(f"✅ {edition} PDF ready: {pdf_path}  ({len(images)} pages)")
    else:
        print(f"❌ {edition} pages not found")


for edition, urdu_slug in editions.items():
    download_edition(edition, urdu_slug, debug_dump=True)
    time.sleep(EDITION_DELAY)
