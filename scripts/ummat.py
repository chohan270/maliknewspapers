import requests
from PIL import Image
from io import BytesIO
from datetime import datetime
import os
from concurrent.futures import ThreadPoolExecutor

# ===== TODAY DATE =====
today = datetime.now()
DAY = today.strftime("%d")
MONTH_NUM = today.strftime("%m")
YEAR = str(today.year)
MONTH_SHORT = today.strftime("%b")

# ===== EDITIONS & LINKS =====
# All editions use a double slash before "images" (matches live site URLs)
BASE = "https://ummat.net/cdn/{year}/{month}/{day}//images/{filename}"

editions = {
    "Karachi": lambda page: f"page-{page}.jpg",
    "Pindi": lambda page: f"page{page}.jpg",
    "Peshawer": lambda page: f"page{page:02d}.jpg",   # matches page01.jpg, page02.jpg ... as given
    "Hyderabad": lambda page: f"page_{page}.jpg",
}

MAX_PAGES = 30
SAVE_FOLDER = "Ummat_PDFs"
os.makedirs(SAVE_FOLDER, exist_ok=True)

# ===== Function =====
def download_edition(edition, filename_fn):
    print(f"\n📖 Downloading {edition} newspaper...")
    images = []
    found_any = False

    for page in range(1, MAX_PAGES + 1):
        filename = filename_fn(page)
        url = BASE.format(year=YEAR, month=MONTH_NUM, day=DAY, filename=filename)
        try:
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                break

            img = Image.open(BytesIO(r.content)).convert("RGB")
            images.append(img)
            found_any = True
            print(f"{edition} - Page {page} added")

        except:
            break

    if found_any:
        pdf_name = f"Ummat {edition} {DAY}{MONTH_SHORT}.pdf"
        pdf_path = os.path.join(SAVE_FOLDER, pdf_name)
        images[0].save(pdf_path, save_all=True, append_images=images[1:])
        print(f"✅ {edition} PDF ready: {pdf_path}")
    else:
        print(f"❌ {edition} pages not found")

# ===== Run all editions =====
with ThreadPoolExecutor(max_workers=4) as executor:
    for edition, filename_fn in editions.items():
        executor.submit(download_edition, edition, filename_fn)
