#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Roznama Sahafat Epaper (sahafat.com.pk) Auto Downloader
===========================================================
Editions (confirmed, seedha site se): Islamabad, Lahore, Karachi,
Peshawar, Muzaffarabad. Default mein sab 5 chalti hain -- agar sirf
kuch chahiye to --editions flag use karein (misaal neeche).

SITE PATTERN (confirmed, seedha URL se):
    Viewer page:
      http://sahafat.com.pk/epaper%20<folder>/<YYYY>/<mon>/<D>/<viewer_file>
    Page images (isi page ke andar seedhi milti hain):
      http://sahafat.com.pk/epaper%20<folder>/<YYYY>/<mon>/<D>/<prefix><page>.jpg

    <folder> aur <prefix> har edition ke alag hain:
        Islamabad     -> folder "isb"     prefix "i"
        Lahore        -> folder "lahore"  prefix "l"
        Karachi       -> folder "karachi" prefix "k"
        Peshawar      -> folder "pew"     prefix "p"
        Muzaffarabad  -> folder "muz"     prefix "m"

    <mon>  = 3-letter lowercase month (jan, feb, mar ... jul, aug ...)
    <D>    = din bina leading zero ke (17, 1, 9, 25 ...)
    <page> = page number bina leading zero ke (1, 2, 3 ... 12 ...)

Script kisi HTML listing pe depend nahi karti -- seedha page 1, 2,
3... try karti hai jab tak DO consecutive pages na milein (isse maan
liya jata hai ke edition khatam ho gaya).

Requirements:
    pip install requests pillow

Usage:
    python sahafat_epaper_downloader.py
    python sahafat_epaper_downloader.py --editions Islamabad Lahore Karachi
    python sahafat_epaper_downloader.py --outdir "C:/SahafatPDFs"
    python sahafat_epaper_downloader.py --keep-images
    python sahafat_epaper_downloader.py --date 17-07-2026   (manual date, DD-MM-YYYY)

Automatic daily run:
-----------------------------------------------------------------
  Windows (Task Scheduler): Daily trigger, program "python", arguments
  "C:\\path\\sahafat_epaper_downloader.py"

  Linux/Mac (cron) -- roz subah 8:00 baje:
    0 8 * * * /usr/bin/python3 /path/sahafat_epaper_downloader.py
"""

import argparse
import concurrent.futures
import io
import os
import sys
import time
from datetime import datetime, timedelta, timezone

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    sys.exit("requests missing hai. Pehle chalayein: pip install requests")

try:
    from PIL import Image, ImageFile
    ImageFile.LOAD_TRUNCATED_IMAGES = True
except ImportError:
    sys.exit("Pillow missing hai. Pehle chalayein: pip install pillow")


BASE = "http://sahafat.com.pk"

# name -> (folder, image_prefix)
EDITIONS = {
    "Islamabad": ("isb", "i"),
    "Lahore": ("lahore", "l"),
    "Karachi": ("karachi", "k"),
    "Peshawar": ("pew", "p"),
    "Muzaffarabad": ("muz", "m"),
}

MONTH_ABBR = [
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
    "Connection": "keep-alive",
}

IMAGE_RETRIES = 4
RETRY_SLEEP = 1.5
REQUEST_TIMEOUT = 40
THREADS_PER_EDITION = 4
MAX_PAGES = 30
STOP_AFTER_CONSECUTIVE_MISSING = 2

PKT = timezone(timedelta(hours=5))


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def make_session():
    s = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=10)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update(HEADERS)
    return s


def build_page_url(folder, prefix, date_obj, page_num):
    year = date_obj.year
    mon = MONTH_ABBR[date_obj.month - 1]
    day = date_obj.day
    return f"{BASE}/epaper%20{folder}/{year}/{mon}/{day}/{prefix}{page_num}.jpg"


def fetch_page_image(session, url):
    last_err = None
    for attempt in range(1, IMAGE_RETRIES + 1):
        try:
            r = session.get(url, timeout=REQUEST_TIMEOUT, stream=True)
            if r.status_code == 404:
                r.close()
                return "missing", None
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}"
                r.close()
            else:
                chunks = []
                for chunk in r.raw.stream(65536, decode_content=True):
                    if chunk:
                        chunks.append(chunk)
                content = b"".join(chunks)
                r.close()

                expected_len = r.headers.get("Content-Length")
                if expected_len is not None and int(expected_len) != len(content):
                    last_err = f"size mismatch (expected {expected_len}, got {len(content)})"
                elif len(content) < 2000:
                    last_err = f"too small ({len(content)} bytes)"
                else:
                    try:
                        im = Image.open(io.BytesIO(content))
                        im.load()
                        return "ok", content
                    except Exception as e:
                        last_err = f"corrupt/truncated image ({e})"
        except requests.RequestException as e:
            last_err = str(e)

        time.sleep(RETRY_SLEEP * attempt)

    log(f"    FAILED after {IMAGE_RETRIES} tries: {url}  ({last_err})")
    return "error", None


def discover_and_download(session, folder, prefix, date_obj, edition_name):
    results = {}
    consecutive_missing = 0
    page_num = 1

    while page_num <= MAX_PAGES and consecutive_missing < STOP_AFTER_CONSECUTIVE_MISSING:
        url = build_page_url(folder, prefix, date_obj, page_num)
        status, content = fetch_page_image(session, url)
        if status == "ok":
            results[page_num] = content
            consecutive_missing = 0
            log(f"    [{edition_name}] page {page_num}: OK ({len(content)} bytes)")
        elif status == "missing":
            consecutive_missing += 1
            log(f"    [{edition_name}] page {page_num}: nahi mila (404)")
        else:
            consecutive_missing = 0
            log(f"    [{edition_name}] page {page_num}: download error, skip kar rahe hain")
        page_num += 1

    return results


def process_edition(edition_name, folder, prefix, date_obj, outdir, keep_images):
    date_str = date_obj.strftime("%d-%m-%Y")
    log(f"==> {edition_name} ({date_str}): pages dhoondi ja rahi hain...")
    session = make_session()

    results = discover_and_download(session, folder, prefix, date_obj, edition_name)
    if not results:
        log(f"==> {edition_name}: koi page nahi mila is date ({date_str}) ke liye.")
        return None

    log(f"==> {edition_name}: {len(results)} pages mile.")

    pil_images = []
    if keep_images:
        tag = f"{edition_name}_{date_str.replace('-', '')}"
        tmp_dir = os.path.join(outdir, "_raw", tag)
        os.makedirs(tmp_dir, exist_ok=True)

    for page_num in sorted(results.keys()):
        content = results[page_num]
        try:
            im = Image.open(io.BytesIO(content))
            im.load()
            im = im.convert("RGB")
        except Exception as e:
            log(f"    [{edition_name}] page {page_num}: open error, skip: {e}")
            continue
        pil_images.append(im)
        if keep_images:
            im.save(os.path.join(tmp_dir, f"{page_num:02d}.jpg"), quality=95)

    if not pil_images:
        log(f"==> {edition_name}: koi bhi page successfully open nahi hua, PDF skip.")
        return None

    os.makedirs(outdir, exist_ok=True)
    pretty_date = date_obj.strftime("%d%B")
    pdf_name = f"Sahafat {edition_name} {pretty_date}.pdf"
    pdf_path = os.path.join(outdir, pdf_name)

    first, rest = pil_images[0], pil_images[1:]
    first.save(pdf_path, save_all=True, append_images=rest)
    log(f"==> {edition_name}: PDF ban gayi -> {pdf_path}  ({len(pil_images)} pages)")
    return pdf_path


def main():
    parser = argparse.ArgumentParser(description="Roznama Sahafat Epaper auto downloader -> PDF")
    parser.add_argument(
        "--editions",
        nargs="+",
        choices=list(EDITIONS.keys()),
        default=None,
        help="Sirf in editions ko download karein (default: sab 5).",
    )
    parser.add_argument(
        "--outdir",
        default=os.path.join(os.getcwd(), "Sahafat_Epaper_PDFs"),
        help="PDF output folder",
    )
    parser.add_argument(
        "--keep-images",
        action="store_true",
        help="Har page ki alag JPG bhi rakhein (_raw folder mein).",
    )
    parser.add_argument(
        "--date",
        default=None,
        metavar="DD-MM-YYYY",
        help="Manual date (default: aaj, PKT). Misaal: --date 17-07-2026",
    )
    args = parser.parse_args()

    if args.date:
        try:
            date_obj = datetime.strptime(args.date, "%d-%m-%Y")
        except ValueError:
            sys.exit("--date ka format DD-MM-YYYY hona chahiye, misaal: 17-07-2026")
    else:
        date_obj = datetime.now(PKT).replace(tzinfo=None)

    os.makedirs(args.outdir, exist_ok=True)
    log(f"Output folder: {args.outdir}")
    log(f"Target date: {date_obj.strftime('%d-%m-%Y')}")

    chosen = args.editions or list(EDITIONS.keys())
    log(f"Editions ({len(chosen)}): {', '.join(chosen)}")

    results = {}
    for name in chosen:
        folder, prefix = EDITIONS[name]
        try:
            path = process_edition(name, folder, prefix, date_obj, args.outdir, args.keep_images)
            results[name] = path
        except Exception as e:
            log(f"==> {name}: UNEXPECTED ERROR -> {e}")
            results[name] = None

    log("")
    log("===================== SUMMARY =====================")
    ok = 0
    for name, path in results.items():
        status = path if path else "FAILED"
        log(f"{name:14s} -> {status}")
        if path:
            ok += 1
    log(f"Total: {ok}/{len(results)} editions successful.")
    log("=====================================================")


if __name__ == "__main__":
    main()
