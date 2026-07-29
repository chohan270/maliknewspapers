import requests
from PIL import Image
from io import BytesIO
from datetime import datetime
import os

# ===== TODAY DATE (M-D-YYYY) =====
today = datetime.now()
DATE_STR = f"{today.month}-{today.day}-{today.year}"  # example: 2-9-2026

# ===== EDITIONS =====
EDITIONS = {
    "Lahore": "lahore",
    "Karachi": "karachi",
    "Rawalpindi": "pindi",
    "Multan": "multan",
    "Quetta": "quetta"
}

BASE_URL = "https://e.jang.com.pk/static_pages/{date}/{edition}/mainpage/page"
MAX_PAGES = 30

headers = {
    "User-Agent": "Mozilla/5.0"
}

os.makedirs("jang_pdfs", exist_ok=True)

for name, edition in EDITIONS.items():
    print(f"\n📘 {name} edition start")
    pdf_images = []

    for page in range(1, MAX_PAGES + 1):
        mila = False

        for ext in ["jpg", "png"]:
            url = BASE_URL.format(
                date=DATE_STR,
                edition=edition
            ) + f"{page}.{ext}"

            print("Try:", url)

            try:
                r = requests.get(url, headers=headers, timeout=10)

                if r.status_code == 200:
                    img = Image.open(BytesIO(r.content)).convert("RGB")
                    pdf_images.append(img)
                    print(f"✅ Page {page} add ho gaya ({ext})")
                    mila = True
                    break
            except:
                pass

        if not mila:
            print(f"❌ {name} page {page} nahi mila, edition complete")
            break

    if pdf_images:
        pdf_path = f"jang_pdfs/{name}_{DATE_STR}.pdf"
        pdf_images[0].save(
            pdf_path,
            save_all=True,
            append_images=pdf_images[1:]
        )
        print(f"📕 PDF ban gayi: {pdf_path}")
    else:
        print(f"⚠️ {name} ki koi page nahi mila")
