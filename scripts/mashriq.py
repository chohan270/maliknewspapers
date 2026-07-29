import requests
from PIL import Image
from io import BytesIO
from datetime import datetime
import os

# ===== TODAY DATE (DD-MM-YYYY) — mashriqtv.pk isi format mein date leta hai =====
today = datetime.now()
DATE_STR = today.strftime("%d-%m-%Y")   # example: 12-07-2026
DAY = today.strftime("%d")
MONTH_SHORT = today.strftime("%b")

# ===== IMAGE URL PATTERN (site se confirmed) =====
# https://mashriqtv.pk/daily-mashriq/uploads/mashriqnp/12-07-2026/mas-12-07-2026-1.jpg
BASE_URL = "https://mashriqtv.pk/daily-mashriq/uploads/mashriqnp/{date}/mas-{date}-{page}.jpg"
MAX_PAGES = 20

headers = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"),
    "Referer": "https://mashriqtv.pk/e-paper/",
}

SAVE_FOLDER = "Mashriq_PDFs"
os.makedirs(SAVE_FOLDER, exist_ok=True)

print("\n📰 Mashriq Peshawar edition start")
pdf_images = []

for page in range(1, MAX_PAGES + 1):
    url = BASE_URL.format(date=DATE_STR, page=page)
    print("Try:", url)

    got = False
    for attempt in range(1, 4):
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                img = Image.open(BytesIO(r.content)).convert("RGB")
                pdf_images.append(img)
                print(f"✅ Page {page} add ho gaya")
                got = True
                break
        except Exception:
            pass

    if not got:
        print(f"❌ Peshawar page {page} nahi mila, edition complete")
        break

if pdf_images:
    pdf_path = os.path.join(SAVE_FOLDER, f"Mashriq Peshawar {DAY}{MONTH_SHORT}.pdf")
    pdf_images[0].save(pdf_path, save_all=True, append_images=pdf_images[1:])
    print(f"📕 PDF ban gayi: {pdf_path}  ({len(pdf_images)} pages)")
else:
    print("⚠️ Koi page nahi mila")
