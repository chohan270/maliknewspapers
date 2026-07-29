import requests
import time
from PIL import Image, ImageFile
from io import BytesIO
from datetime import datetime
import os

ImageFile.LOAD_TRUNCATED_IMAGES = True

# Same platform as dailyghaznavi.com — confirmed pattern:
# https://mahasib.com.pk/assets/{edition}/{date}/{page}.jpg

today = datetime.now()
DATE = today.strftime("%d-%m-%Y")   # e.g. 19-07-2026
DAY = today.strftime("%d")
MONTH_SHORT = today.strftime("%b")

# ===== EDITIONS (confirmed from site's "Select Edition" dropdown) =====
editions = {
    "Muzzaffarabad": "muzzaffarabad",
    "Abbottabad": "abbottabad",
    "Gilgit": "gilgit",
}

IMG_URL = "https://mahasib.com.pk/assets/{edition}/{date}/{page}.jpg"
MAX_PAGES = 12
MAX_RETRIES = 3
PAGE_DELAY = 0.5

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"),
}

SAVE_FOLDER = "Mahasib_PDFs"
os.makedirs(SAVE_FOLDER, exist_ok=True)


def download_edition(edition, slug):
    print(f"\n📖 Downloading {edition} newspaper...")
    session = requests.Session()
    images = []

    for page in range(1, MAX_PAGES + 1):
        url = IMG_URL.format(edition=slug, date=DATE, page=page)
        img = None
        last_status = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                r = session.get(url, headers=HEADERS, timeout=15)
                last_status = r.status_code
                if r.status_code == 200 and len(r.content) > 1000:
                    img = Image.open(BytesIO(r.content)).convert("RGB")
                    break
            except Exception:
                pass
            time.sleep(1.0 * attempt)

        if img is None:
            print(f"  ℹ️  {edition} page {page}: not available (HTTP {last_status}) — stopping here.")
            break

        images.append(img)
        print(f"{edition} - Page {page} added")
        time.sleep(PAGE_DELAY)

    if images:
        pdf_name = f"Mahasib {edition} {DAY}{MONTH_SHORT}.pdf"
        pdf_path = os.path.join(SAVE_FOLDER, pdf_name)
        images[0].save(pdf_path, save_all=True, append_images=images[1:])
        print(f"✅ {edition} PDF ready: {pdf_path}  ({len(images)} pages)")
    else:
        print(f"❌ {edition} pages not found")


for edition, slug in editions.items():
    download_edition(edition, slug)
    time.sleep(1.5)
