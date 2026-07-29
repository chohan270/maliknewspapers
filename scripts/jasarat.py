#!/usr/bin/env python3
"""
Jasarat Epaper Downloader -> PDF
=================================
Target: https://jasarat.news

Direct Image URL Pattern:
  https://jasarat.news/{edition}/images/dates/{YYYY-MM-DD}/{edition}/mm/{page}.jpg

Supported Editions:
  - karachi
  - hyderabad  
  - islamabad

Example:
  https://jasarat.news/karachi/images/dates/2026-07-19/karachi/mm/1.jpg
  https://jasarat.news/hyderabad/images/dates/2026-07-19/hyderabad/mm/1.jpg
  https://jasarat.news/islamabad/images/dates/2026-07-19/islamabad/mm/1.jpg

Install:
    pip install pillow requests --break-system-packages

Usage:
    python3 jasarat_epaper_downloader.py
    python3 jasarat_epaper_downloader.py --editions karachi hyd
    python3 jasarat_epaper_downloader.py --date 2026-07-18
    python3 jasarat_epaper_downloader.py --editions islamabad karachi --date 2026-07-17
"""

import argparse
import io
import os
import sys
import time
from datetime import datetime, timedelta, timezone

from PIL import Image

try:
    import requests
except ImportError:
    print("requests install nahi hai. Ye chalayein:")
    print("    pip install pillow requests --break-system-packages")
    sys.exit(1)


BASE = "https://jasarat.news"

PKT = timezone(timedelta(hours=5))  # Pakistan Standard Time

EDITIONS = {
    "karachi": "Karachi",
    "hyderabad": "Hyderabad",
    "hyd": "Hyderabad",  # alias
    "islamabad": "Islamabad",
}

# Har edition ke URL mein jo "folder naam" aata hai wo hamesha city ke
# naam se match nahi karta -- Karachi ka apna image-folder "epaper" hai
# (city naam "karachi" nahi), jabke Hyderabad/Islamabad apne city-naam
# wala folder use karte hain. Isi liye har edition ke liye candidate
# folders ki list rakhi hai -- jo bhi pehle kaam kar jaye wahi use hoga.
FOLDER_CANDIDATES = {
    "karachi": ["epaper", "karachi"],
    "hyderabad": ["hyderabad", "epaper"],
    "hyd": ["hyderabad", "epaper"],
    "islamabad": ["islamabad", "epaper"],
}

REQUEST_TIMEOUT = 20
MAX_PAGES_TO_TRY = 20


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def today_pkt_dashed():
    """Pakistan time ke hisaab se 'aaj' -- YYYY-MM-DD format."""
    now = datetime.now(PKT)
    return f"{now.year}-{now.month:02d}-{now.day:02d}"


def download_page_image(session, edition, date_str, page_num, known_folder=None, verbose_fail=False):
    """
    Diye gaye edition, date, aur page number ke liye image download karta hai.

    URL pattern:
      https://jasarat.news/{folder}/images/dates/{YYYY-MM-DD}/{edition}/mm/{page}.jpg

    `folder` hamesha edition ke naam jaisa nahi hota (Karachi ke liye
    "epaper" hai), isliye FOLDER_CANDIDATES ki list se try karte hain.
    Agar `known_folder` diya ho (pichle successful page se), sirf wahi
    try karte hain -- taake har page ke liye dobara guess na karna pade.

    Returns:
        (content_bytes_or_None, working_folder_or_None)
    """
    edition_normalized = edition.lower()
    if edition_normalized == "hyd":
        edition_normalized = "hyderabad"

    folders_to_try = [known_folder] if known_folder else FOLDER_CANDIDATES.get(
        edition_normalized, [edition_normalized, "epaper"]
    )

    for folder in folders_to_try:
        url = f"{BASE}/{folder}/images/dates/{date_str}/{edition_normalized}/mm/{page_num}.jpg"
        try:
            r = session.get(url, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200 and len(r.content) > 1000:
                return r.content, folder
            if verbose_fail:
                log(f"    tried: {url} -> status={r.status_code}, size={len(r.content)}")
        except Exception as e:
            if verbose_fail:
                log(f"    tried: {url} -> error: {e}")

    return None, None


def process_edition(session, edition, date_str, outdir):
    """
    Diye gaye edition ke liye poori epaper download karta hai.
    """
    edition_key = edition.lower()
    edition_name = EDITIONS.get(edition_key, edition.title())
    
    log(f"==> {edition_name} ({date_str})")
    
    images_bytes = []
    consecutive_fails = 0
    known_folder = None
    
    for page_num in range(1, MAX_PAGES_TO_TRY + 1):
        content, used_folder = download_page_image(
            session, edition, date_str, page_num,
            known_folder=known_folder,
            verbose_fail=(page_num == 1 and known_folder is None),
        )
        
        if content is not None:
            if known_folder is None:
                known_folder = used_folder
                log(f"    (folder pattern mil gaya: /{used_folder}/images/dates/...)")
            images_bytes.append(content)
            log(f"    Page {page_num}: OK ({len(content)} bytes)")
            consecutive_fails = 0
        else:
            consecutive_fails += 1
            
            # Agar 3 pages ek dam fail hue to assume edition khatam ho gaya
            if consecutive_fails >= 3:
                if page_num == 1:
                    log(f"    Page {page_num}: FAIL (edition nahi mil raha)")
                else:
                    log(f"    -> {consecutive_fails} pages ek dam fail hue, edition khatam.")
                break
        
        # Throttle taake server par load na padhe
        time.sleep(0.3)
    
    if not images_bytes:
        log(f"==> {edition_name}: koi page download nahi hua.")
        return None
    
    # PDF banao
    os.makedirs(outdir, exist_ok=True)
    pil_images = []
    
    for i, content in enumerate(images_bytes):
        try:
            im = Image.open(io.BytesIO(content))
            im.load()
            im = im.convert("RGB")
            pil_images.append(im)
        except Exception as e:
            log(f"    Page {i+1} image open fail: {e}")
            continue
    
    if not pil_images:
        log(f"==> {edition_name}: koi page successfully load nahi hua.")
        return None
    
    # PDF filename
    pretty_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d%B")  # e.g., "19July"
    pdf_name = f"Jasarat {edition_name} {pretty_date}.pdf"
    pdf_path = os.path.join(outdir, pdf_name)
    
    try:
        first, rest = pil_images[0], pil_images[1:]
        first.save(pdf_path, save_all=True, append_images=rest)
        log(f"==> {edition_name}: PDF ban gayi -> {pdf_path} ({len(pil_images)} pages)")
        return pdf_path
    except Exception as e:
        log(f"==> {edition_name}: PDF save fail: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Jasarat Epaper Downloader -> PDF",
        epilog="Examples:\n"
               "  python3 jasarat_epaper_downloader.py\n"
               "  python3 jasarat_epaper_downloader.py --editions karachi hyd\n"
               "  python3 jasarat_epaper_downloader.py --date 2026-07-18\n"
               "  python3 jasarat_epaper_downloader.py --editions islamabad karachi --date 2026-07-17",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--editions",
        nargs="+",
        default=["karachi", "hyderabad", "islamabad"],
        help="Editions to download (default: karachi hyderabad islamabad -- sab). Options: karachi, hyderabad/hyd, islamabad",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Date in YYYY-MM-DD format (default: aaj, Pakistan time)",
    )
    parser.add_argument(
        "--outdir",
        default=os.path.join(os.getcwd(), "Jasarat_Epaper_PDFs"),
        help="Output folder for PDFs (default: ./Jasarat_Epaper_PDFs)",
    )
    args = parser.parse_args()

    # Parse date
    if args.date:
        try:
            y, m, d = map(int, args.date.split("-"))
            date_str = f"{y}-{m:02d}-{d:02d}"
        except ValueError:
            log("ERROR: Date must be YYYY-MM-DD format")
            sys.exit(1)
    else:
        date_str = today_pkt_dashed()

    log(f"Date: {date_str}")
    log(f"Editions: {', '.join(args.editions)}")
    log(f"Output folder: {args.outdir}")

    os.makedirs(args.outdir, exist_ok=True)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })

    results = {}
    for edition in args.editions:
        try:
            results[edition] = process_edition(session, edition, date_str, args.outdir)
        except Exception as e:
            log(f"==> {edition}: ERROR -> {e}")
            results[edition] = None

    log("")
    log("===================== SUMMARY =====================")
    ok = 0
    for edition, path in results.items():
        edition_name = EDITIONS.get(edition.lower(), edition.title())
        status = path if path else "FAILED"
        log(f"{edition_name:15s} -> {status}")
        if path:
            ok += 1
    log(f"Total: {ok}/{len(results)} editions successful.")
    log("===================================================")


if __name__ == "__main__":
    main()
