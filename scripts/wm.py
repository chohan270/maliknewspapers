#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Existing PDF Watermark (FRONT PAGE ONLY) + Merge Tool
==========================================================================
Malik Qasim Raza Chohan

Ye tool AAP KI PEHLE SE MAUJOOD PDFs par kaam karta hai.

YE 2 CHEEZEIN KARTA HAI:
------------------------
1) WATERMARK: SIRF PEHLE PAGE (front page, jahan epaper ka naam likha
   hota hai) par watermark PNG permanently "flatten" (hard-burn) kar
   deta hai. BAAKI pages ko HAATH TAK NAHI LAGATA -- woh original PDF
   se bilkul jaisi ki taisi (byte-for-byte) copy hoti hain.

   WATERMARK LOGIC -- SAARE epapers par same rule (Express ho ya koi
   bhi aur naam):
       * Agar front page ke header ke UPAR White space khali ho
         -> express.png laga do, TOP-CENTER par, 70% size, 0.4%
            margin, 100% opacity.
       * Agar header edge ke sath (bina white space ke) lag raha ho
         -> pbk.png laga do, TOP-RIGHT corner par (jaisa pehle tha).

   Dono cases mein watermark hard-burned/flatten hoti hai (permanent,
   PNG layer nahi -- image ke andar seedha bake ho jati hai).

2) MERGE: PDF ke bilkul AAKHIR mein EXTRA_LAST_PDF jod deta hai --
   isliye final file size sirf usi extra PDF jitni barhti hai, baaki
   kuch nahi badalta.

NOTE (Heroku build): Ye file wm.py ke original logic se BILKUL same
hai -- sirf CONFIG section ke paths ab is repo ke andar 'scripts/assets/'
folder aur /tmp (Heroku ki ephemeral, writable jagah) ki taraf point
karte hain, taake Android/Termux ke hardcoded /storage/... paths ki
zaroorat na rahe. process_pdf() function ko epaper_scheduler.py seedha
import karke, har PDF ke liye alag se call karta hai.

Requirements:
    pip install pypdf pillow
"""

import io
import os
import time

from PIL import Image
from pypdf import PdfReader, PdfWriter

# ===================== CONFIG =====================

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ASSETS_DIR = os.path.join(_SCRIPT_DIR, "assets")

# Standalone/manual-run mode only (epaper_scheduler.py calls process_pdf()
# directly and does not use INPUT_PATH / OUTPUT_FOLDER at all).
INPUT_PATH = os.environ.get("EPAPER_WM_INPUT", "")
OUTPUT_FOLDER = os.environ.get("EPAPER_WM_OUTPUT", "/tmp/epaper_watermarked")

# ---- Default watermark (baaqi saare epapers + Express jab header edge
#      ke sath lagi ho) -- TOP-RIGHT corner ----
WATERMARK_PNG = os.path.join(_ASSETS_DIR, "pbk.png")
WATERMARK_WIDTH_PERCENT = 25
WATERMARK_MARGIN_PERCENT = 0.1

# ---- Express-only watermark (jab header ke upar white space ho) ----
#      TOP-CENTER, 70% size, 0.4% margin, 100% opacity
EXPRESS_WATERMARK_PNG = os.path.join(_ASSETS_DIR, "express.png")
EXPRESS_WIDTH_PERCENT = 70
EXPRESS_MARGIN_PERCENT = 0.4
EXPRESS_OPACITY_PERCENT = 100

# ---- White-space detection settings (front page ke TOP par) ----
TOP_SCAN_LIMIT_PERCENT = 15      # zyada se zyada image ke top kitne % tak scan karein
WHITESPACE_ROW_RATIO = 0.90      # ek row "white" tab manegi jab uske itne % pixels white hon
WHITESPACE_BRIGHTNESS = 235      # 0-255, isse upar wala pixel "white" mana jayega
WHITESPACE_MIN_PERCENT = 1.0     # white band agar page height ke itne % se zyada ho, to "whitespace hai"

EXTRA_LAST_PDF = os.path.join(_ASSETS_DIR, "pbk.pdf")

# ===================================================

os.makedirs(OUTPUT_FOLDER, exist_ok=True)


def has_top_whitespace(img):
    """Top se neeche row-by-row scan karta hai aur pata karta hai ke
    header shuru hone se pehle asal mein kitni height ka white/khali
    band hai. Agar wo band WHITESPACE_MIN_PERCENT se zyada ho to True
    (whitespace hai) deta hai, warna False (header edge ke sath lag
    raha hai)."""
    gray = img.convert("L")
    w, h = gray.size
    max_scan = max(1, int(h * TOP_SCAN_LIMIT_PERCENT / 100))

    white_band_height = 0
    for y in range(max_scan):
        row = gray.crop((0, y, w, y + 1))
        hist = row.histogram()
        white_count = sum(hist[WHITESPACE_BRIGHTNESS:])
        frac_white = white_count / w
        if frac_white >= WHITESPACE_ROW_RATIO:
            white_band_height = y + 1
        else:
            break  # yahan se header/content shuru ho gaya

    band_percent = (white_band_height / h) * 100
    return band_percent >= WHITESPACE_MIN_PERCENT


def pick_watermark_settings(img):
    """Front page ke top white-space check ke hisaab se decide karta
    hai ke kaunsi watermark PNG, kis size/margin/position/opacity ke
    sath lagegi -- ye rule HAR epaper par same lagta hai (Express ho
    ya koi bhi aur naam). Returns: (png_path, width_percent,
    margin_percent, position, opacity_percent)"""
    if os.path.exists(EXPRESS_WATERMARK_PNG) and has_top_whitespace(img):
        return (
            EXPRESS_WATERMARK_PNG,
            EXPRESS_WIDTH_PERCENT,
            EXPRESS_MARGIN_PERCENT,
            "top-center",
            EXPRESS_OPACITY_PERCENT,
        )

    return (
        WATERMARK_PNG,
        WATERMARK_WIDTH_PERCENT,
        WATERMARK_MARGIN_PERCENT,
        "top-right",
        100,
    )


def apply_watermark(img, png_path, width_percent, margin_percent, position, opacity_percent):
    """Watermark PNG ko diye gaye position (top-right / top-center) par,
    diye gaye size/margin/opacity ke sath permanently flatten kar deta
    hai."""
    if not png_path or not os.path.exists(png_path):
        return img

    wm = Image.open(png_path).convert("RGBA")
    base_w, base_h = img.size

    wm_w = max(1, int(base_w * width_percent / 100))
    wm_h = max(1, int(wm.height * (wm_w / wm.width)))
    wm = wm.resize((wm_w, wm_h), Image.LANCZOS)

    if opacity_percent < 100:
        alpha = wm.split()[3]
        alpha = alpha.point(lambda p: int(p * (opacity_percent / 100)))
        wm.putalpha(alpha)

    margin_x = int(base_w * margin_percent / 100)
    margin_y = int(base_h * margin_percent / 100)

    if position == "top-center":
        pos = ((base_w - wm_w) // 2, margin_y)
    else:  # "top-right"
        pos = (base_w - wm_w - margin_x, margin_y)

    canvas = img.convert("RGBA")
    canvas.paste(wm, pos, wm)      # wm khud apna alpha-mask hai
    return canvas.convert("RGB")   # flatten -> ab permanent (hard-burned) hai


def build_watermarked_front_page(reader):
    """Page 1 ki embedded image nikaal kar sahi watermark laga ke,
    usse ek naya single-page PDF object bana deta hai. Agar page 1
    mein koi image na mile to None deta hai (front page bhi as-is
    copy ho jayega)."""
    front_page = reader.pages[0]
    imgs = front_page.images
    if not imgs:
        return None

    img = imgs[0].image.convert("RGB")

    png_path, width_percent, margin_percent, position, opacity_percent = pick_watermark_settings(img)
    img = apply_watermark(img, png_path, width_percent, margin_percent, position, opacity_percent)

    buf = io.BytesIO()
    img.save(buf, format="PDF")
    buf.seek(0)
    return PdfReader(buf).pages[0]


def process_pdf(pdf_path, output_path):
    """Public entrypoint -- epaper_scheduler.py isko har raw PDF ke liye
    seedha call karta hai (import karke), koi subprocess nahi chahiye."""
    print(f"\n📄 Processing: {pdf_path}")
    reader = PdfReader(pdf_path)
    writer = PdfWriter()

    watermarked_front = build_watermarked_front_page(reader)
    if watermarked_front is not None:
        writer.add_page(watermarked_front)
        print("  ✅ Page 1 (front page) watermark ho gaya")
    else:
        writer.add_page(reader.pages[0])
        print("  ⚠️ Page 1 mein image nahi mili, watermark skip (as-is copy)")

    for i in range(1, len(reader.pages)):
        writer.add_page(reader.pages[i])

    if EXTRA_LAST_PDF and os.path.exists(EXTRA_LAST_PDF):
        for p in PdfReader(EXTRA_LAST_PDF).pages:
            writer.add_page(p)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "wb") as f:
        writer.write(f)

    print(f"  ✅ Final PDF ready: {output_path}  ({len(writer.pages)} pages)")
    return output_path


if __name__ == "__main__":
    # Manual/standalone mode (not used by epaper_scheduler.py):
    #   EPAPER_WM_INPUT=/path/to/folder-or-file python3 wm.py
    start = time.time()

    if not INPUT_PATH:
        print("ℹ️  Standalone mode: set EPAPER_WM_INPUT env var to a folder or a single PDF.")
    elif os.path.isdir(INPUT_PATH):
        pdfs = [
            f for f in os.listdir(INPUT_PATH)
            if f.lower().endswith(".pdf") and f.lower() != "pbk.pdf"
        ]
        if not pdfs:
            print(f"❌ '{INPUT_PATH}' folder mein koi PDF nahi mili")
        for name in pdfs:
            in_path = os.path.join(INPUT_PATH, name)
            out_path = os.path.join(OUTPUT_FOLDER, name)
            process_pdf(in_path, out_path)

    elif os.path.isfile(INPUT_PATH):
        out_path = os.path.join(OUTPUT_FOLDER, os.path.basename(INPUT_PATH))
        process_pdf(INPUT_PATH, out_path)

    else:
        print(f"❌ INPUT_PATH nahi mila: {INPUT_PATH}")

    print(f"\n⏱️  Total time: {time.time() - start:.2f} seconds")
