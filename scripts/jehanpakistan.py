#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daily Jehan Pakistan Epaper (jehanpakistan.com) Auto Downloader
==================================================================
5 editions (Lahore, Karachi, Islamabad, Multan, Gujranwala) ka aaj ka
epaper auto-download kar ke har edition ki PDF bana deta hai.

SITE PATTERN (jehanpakistan.com/epaper/ analyze karke maloom hua):
--------------------------------------------------------------------
1) Home page (https://jehanpakistan.com/epaper/) per 5 edition links
   hain, har link is form mein hai:
       https://jehanpakistan.com/epaper/epaper.php?edition=lahore&date=160726
   Date format = DDMMYY (din, mahina, saal ke aakhri 2 digit).
   Editions ke slugs: lahore, karachi, islamabad, multan, gujranwala

2) epaper.php?edition=<slug>&date=<DDMMYY> per us edition ke saare
   pages ki THUMBNAIL images dikhti hain, is pattern se:
       https://jehanpakistan.com/epaper/epaper/<slug>/<date>/thumb_<FILENAME>.jpg
   FILENAME har page/din alag hoti hai (jaise "PAGE01-16JULY-26-LHR.jpg")
   aur consistent formula nahi follow karti (kabhi purani date bhi
   dikh jaati hai filename mein) -- is liye Express/Khabrain ki tarah
   yeh script bhi har baar live HTML se hi filenames nikaalti hai,
   hardcode nahi karti.

3) Full-resolution image -- jaisa Express (nation.com.pk group) mein
   hota hai -- waisi hi is site per bhi lagta hai ke "thumb_" prefix
   hata kar full image milni chahiye:
       https://jehanpakistan.com/epaper/epaper/<slug>/<date>/<FILENAME>.jpg
   ** NOTE: Yeh pattern maine site ka HTML/structure dekh kar andaza
   lagaya hai (Express jaisa hi convention), lekin isay directly
   test/fetch nahi kar saka is environment mein (yahan internet access
   nahi hai). Is liye script ne ehtiyaat rakhi hai -- agar full-res URL
   404 de ya kaam na kare, to khud-ba-khud thumbnail hi download kar
   leti hai (kam quality sahi, lekin PDF phir bhi mukammal banegi).
   Agar full-res kaam na kare to bas iski line neeche FULL_URL_PATTERN
   mein URL edit kar dein jab asal pattern pata chal jaye. **

4) Agar kisi edition ki listing na mile (site down / aaj ka issue
   abhi upload nahi hua) to sirf wo edition skip hoti hai, baqi
   editions download hoti rehti hain.

Requirements:
    pip install requests pillow

Usage:
    python jehanpakistan.py
"""

import os
import re
import time
from datetime import datetime
from io import BytesIO

import requests
from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True  # tolerate slightly incomplete responses

# ===== TODAY DATE (DDMMYY -- jehanpakistan.com isi format mein date leta hai) =====
today = datetime.now()
DATE = today.strftime("%d%m%y")     # example: 16-Jul-2026 -> "160726"
DAY = today.strftime("%d")
MONTH_SHORT = today.strftime("%b")

# ===== EDITIONS (city name -> url slug, jaisa site per confirmed hai) =====
EDITIONS = {
    "Lahore": "lahore",
    "Karachi": "karachi",
    "Islamabad": "islamabad",
    "Multan": "multan",
    "Gujranwala": "gujranwala",
}

LIST_URL = "https://jehanpakistan.com/epaper/epaper.php"
IMG_BASE = "https://jehanpakistan.com/epaper/epaper/{edition}/{date}"

MAX_RETRIES = 3
PAGE_DELAY = 0.5      # thoda ruk kar agli page maangna, site per load kam
EDITION_DELAY = 2.0   # ek edition ke baad dusri shuru karne se pehle chhota wapqa

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://jehanpakistan.com/epaper/",
}

# thumb_PAGE01-16JULY-26-LHR.jpg jaisi filenames HTML mein dhoondne ka pattern
IMG_PATTERN = re.compile(
    r'epaper/epaper/[a-zA-Z]+/\d+/thumb_([^"\'\s\)]+\.jpg)',
    re.IGNORECASE,
)

SAVE_FOLDER = "JehanPakistan_PDFs"
os.makedirs(SAVE_FOLDER, exist_ok=True)

session = requests.Session()
session.headers.update(HEADERS)


def get_page_filenames(edition_slug):
    """Edition ki listing page se sab page filenames nikaalta hai (order
    wahi rehta hai jo site per dikhti hai, yani PAGE01, PAGE02...)."""
    url = f"{LIST_URL}?edition={edition_slug}&date={DATE}"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, timeout=15)
            if r.status_code == 200 and r.text:
                filenames = IMG_PATTERN.findall(r.text)
                if filenames:
                    return filenames
        except Exception as e:
            print(f"   listing fetch fail (koshish {attempt}): {e}")
        time.sleep(1.5 * attempt)
    return []


def download_page_image(edition_slug, filename):
    """Pehle full-resolution image try karta hai (thumb_ hata kar), agar
    wo na chale to thumbnail hi download kar leta hai taake page miss
    na ho -- bas quality kam hogi."""
    base = IMG_BASE.format(edition=edition_slug, date=DATE)
    full_url = f"{base}/{filename}"
    thumb_url = f"{base}/thumb_{filename}"

    for url, is_full in ((full_url, True), (thumb_url, False)):
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                r = session.get(url, timeout=15)
                if r.status_code == 200:
                    img = Image.open(BytesIO(r.content)).convert("RGB")
                    return img, is_full
            except Exception:
                pass
            time.sleep(1.0 * attempt)
    return None, False


def download_edition(name, slug):
    print(f"\n📰 {name} edition start")
    filenames = get_page_filenames(slug)

    if not filenames:
        print(f"❌ {name}: listing nahi mili (site down ya aaj ka issue abhi upload nahi hua)")
        return

    print(f"   {len(filenames)} pages mile")
    images = []
    thumb_fallback_count = 0

    for i, filename in enumerate(filenames, 1):
        img, was_full = download_page_image(slug, filename)
        if img is None:
            print(f"   ⚠️ page {i} download nahi ho saki, skip")
            continue

        images.append(img)
        if not was_full:
            thumb_fallback_count += 1
        tag = "" if was_full else " (thumbnail quality -- full-res URL kaam nahi kiya)"
        print(f"   ✅ page {i} add ho gaya{tag}")
        time.sleep(PAGE_DELAY)

    if images:
        pdf_name = f"JehanPakistan {name} {DAY}{MONTH_SHORT}.pdf"
        pdf_path = os.path.join(SAVE_FOLDER, pdf_name)
        images[0].save(pdf_path, save_all=True, append_images=images[1:])
        note = f"  ({thumb_fallback_count} thumbnail-quality pages)" if thumb_fallback_count else ""
        print(f"📕 PDF ban gayi: {pdf_path}  ({len(images)} pages){note}")
    else:
        print(f"⚠️ {name}: koi page download nahi ho saka")


# ===== Run all editions =====
for name, slug in EDITIONS.items():
    download_edition(name, slug)
    time.sleep(EDITION_DELAY)
