#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
The Kawish Epaper (thekawish.com/beta) Auto Downloader -- AAJ KI TAREEKH
==========================================================================
Sirf EK edition hoti hai (Hyderabad) -- koi city selection ki zaroorat
nahi.

SITE PATTERN (confirmed, seedha URL se):
    https://www.thekawish.com/beta/images/<YYYY>/<MonthName>/<DD-MM-YYYY>/<page>.jpg
    (page number 2-digit hota hai: 01, 02, 03 ...)

NOTE: Kawish ka aaj ka edition aam taur par SHAAM 7-8 baje tak upload
hota hai. Agar subah/dopeher chalayenge to "0 pages mile" ya "PDF skip"
aa sakta hai -- ye normal hai, matlab aaj ka issue abhi upload nahi
hua. Shaam ko dobara try karein.

Script kisi HTML listing page pe depend nahi karti -- seedha page 1,
2, 3... try karti hai jab tak DO consecutive pages na milein (isse
maan liya jata hai ke edition khatam ho gaya).

Requirements:
    pip install requests pillow

Usage:
    python kawish_epaper_downloader.py
    python kawish_epaper_downloader.py --outdir "C:/KawishPDFs"
    python kawish_epaper_downloader.py --keep-images
    python kawish_epaper_downloader.py --date 16-07-2026   (manual date, DD-MM-YYYY)

Automatic daily run (roz SHAAM ko chalayein, kyunke edition der se aata hai):
-----------------------------------------------------------------
  Windows (Task Scheduler): Daily trigger ~8:30 PM, program "python",
  arguments "C:\\path\\kawish_epaper_downloader.py"

  Linux/Mac (cron) -- roz raat 8:30 baje:
    30 20 * * * /usr/bin/python3 /path/kawish_epaper_downloader.py
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


BASE = "https://www.thekawish.com/beta"

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
    "Referer": BASE + "/index.php",
    "Connection": "keep-alive",
}

IMAGE_RETRIES = 4
RETRY_SLEEP = 1.5
REQUEST_TIMEOUT = 40
THREADS = 4
MAX_PAGES = 30            # itne se zyada pages kabhi nahi hotin
STOP_AFTER_CONSECUTIVE_MISSING = 2  # do lagataar 404 = edition khatam

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


def build_page_url(date_obj, page_num):
    year = date_obj.year
    month_name = MONTH_NAMES[date_obj.month - 1]
    date_part = date_obj.strftime("%d-%m-%Y")
    return f"{BASE}/images/{year}/{month_name}/{date_part}/{page_num:02d}.jpg"


def fetch_page_image(session, url):
    """
    Return (status, content):
      status = "ok"      -> content hai
      status = "missing" -> confirmed 404 (page exist nahi karta)
      status = "error"   -> network/other issue (retries ke baad bhi)
    """
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


def discover_and_download(session, date_obj):
    """
    Page 1, 2, 3... try karta hai jab tak
    STOP_AFTER_CONSECUTIVE_MISSING lagataar pages "missing" (404) na
    milein. Har mile hue page ka content return karta hai.
    """
    results = {}  # page_num -> content
    consecutive_missing = 0
    page_num = 1

    while page_num <= MAX_PAGES and consecutive_missing < STOP_AFTER_CONSECUTIVE_MISSING:
        url = build_page_url(date_obj, page_num)
        status, content = fetch_page_image(session, url)
        if status == "ok":
            results[page_num] = content
            consecutive_missing = 0
            log(f"    page {page_num}: OK ({len(content)} bytes)")
        elif status == "missing":
            consecutive_missing += 1
            log(f"    page {page_num}: nahi mila (404)")
        else:
            # Network error hone par bhi is page ko "missing" nahi maante
            # (taake ek transient glitch se poori edition truncate na ho),
            # lekin loop ko age barhaate hain.
            consecutive_missing = 0
            log(f"    page {page_num}: download error, skip kar rahe hain")
        page_num += 1

    return results


def process_kawish(date_obj, outdir, keep_images):
    date_str = date_obj.strftime("%d-%m-%Y")
    log(f"==> Kawish Hyderabad ({date_str}): pages dhoondi ja rahi hain...")
    session = make_session()

    results = discover_and_download(session, date_obj)
    if not results:
        log(f"==> Kawish: koi page nahi mila is date ({date_str}) ke liye. "
            f"Agar ye aaj ki date hai to shaam 7-8 baje ke baad dobara try karein "
            f"(edition abhi upload nahi hua ho sakta).")
        return None

    log(f"==> Kawish: {len(results)} pages mile.")

    pil_images = []
    if keep_images:
        tag = f"Kawish_{date_str.replace('-', '')}"
        tmp_dir = os.path.join(outdir, "_raw", tag)
        os.makedirs(tmp_dir, exist_ok=True)

    for page_num in sorted(results.keys()):
        content = results[page_num]
        try:
            im = Image.open(io.BytesIO(content))
            im.load()
            im = im.convert("RGB")
        except Exception as e:
            log(f"    page {page_num}: open error, skip: {e}")
            continue
        pil_images.append(im)
        if keep_images:
            im.save(os.path.join(tmp_dir, f"{page_num:02d}.jpg"), quality=95)

    if not pil_images:
        log("==> Kawish: koi bhi page successfully open nahi hua, PDF skip.")
        return None

    os.makedirs(outdir, exist_ok=True)
    pretty_date = date_obj.strftime("%d%B")
    pdf_name = f"Kawish Hyderabad {pretty_date}.pdf"
    pdf_path = os.path.join(outdir, pdf_name)

    first, rest = pil_images[0], pil_images[1:]
    first.save(pdf_path, save_all=True, append_images=rest)
    log(f"==> Kawish: PDF ban gayi -> {pdf_path}  ({len(pil_images)} pages)")
    return pdf_path


def main():
    parser = argparse.ArgumentParser(description="The Kawish Epaper auto downloader -> PDF (aaj ki tareekh)")
    parser.add_argument(
        "--outdir",
        default=os.path.join(os.getcwd(), "Kawish_Epaper_PDFs"),
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
        help="Manual date (default: aaj, PKT). Misaal: --date 16-07-2026",
    )
    args = parser.parse_args()

    if args.date:
        try:
            date_obj = datetime.strptime(args.date, "%d-%m-%Y")
        except ValueError:
            sys.exit("--date ka format DD-MM-YYYY hona chahiye, misaal: 16-07-2026")
    else:
        date_obj = datetime.now(PKT).replace(tzinfo=None)

    os.makedirs(args.outdir, exist_ok=True)
    log(f"Output folder: {args.outdir}")
    log(f"Target date: {date_obj.strftime('%d-%m-%Y')}")

    try:
        path = process_kawish(date_obj, args.outdir, args.keep_images)
    except Exception as e:
        log(f"UNEXPECTED ERROR -> {e}")
        path = None

    log("")
    log("===================== SUMMARY =====================")
    log(f"Kawish Hyderabad -> {path if path else 'FAILED'}")
    log("=====================================================")


if __name__ == "__main__":
    main()
