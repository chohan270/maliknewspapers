import requests
from PIL import Image
from io import BytesIO
from datetime import datetime
import os

# ===== TODAY DATE (M-D-YYYY) =====
today = datetime.now()
DATE_STR = f"{today.month}-{today.day}-{today.year}"  # example: 7-12-2026

# ===== EDITIONS =====
EDITIONS = {
    "Lahore": "lahore",
    "Karachi": "karachi",
    "Rawalpindi": "pindi",
    "Multan": "multan",
    "Quetta": "quetta"
}

# Sunday Magazine ki images bhi "mainpage" folder ke andar hoti hain,
# bas filename "sunday-magazine-pageN.jpg" hota hai (normal "pageN.jpg" nahi)
BASE_URL = "https://e.jang.com.pk/static_pages/{date}/{edition}/mainpage/sunday-magazine-page"
MAX_PAGES = 20  # Sunday magazine usually 15 pages tak hoti hai, thora buffer rakha hai

headers = {
    "User-Agent": "Mozilla/5.0"
}

os.makedirs("jang_sunday_magazine_pdfs", exist_ok=True)

for name, edition in EDITIONS.items():
    print(f"\n📘 {name} Sunday Magazine start")
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
            print(f"❌ {name} Sunday Magazine page {page} nahi mila, edition complete")
            break

    if pdf_images:
        pdf_path = f"jang_sunday_magazine_pdfs/{name}_SundayMagazine_{DATE_STR}.pdf"
        pdf_images[0].save(
            pdf_path,
            save_all=True,
            append_images=pdf_images[1:]
        )
        print(f"📕 PDF ban gayi: {pdf_path}")
    else:
        print(f"⚠️ {name} Sunday Magazine ki koi page nahi mili")
