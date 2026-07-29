#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daily Parliament Times Epaper (e.dailyparliamenttimes.com) Auto Downloader
=============================================================================
Editions: Islamabad, Quetta, AJK (site ke andar iska slug "muzaffarabad" hai).

SITE PATTERN (scrape se maloom hua):
-------------------------------------
Ye site sab se simple nikli -- EK hi request mein us din ke SAARE pages
ki images seedhi mil jati hain (Khabrain/CountryNews jaisa har page ke
liye alag request karne ki zaroorat NAHI hai):

    https://e.dailyparliamenttimes.com/e/<edition>/?dt=<YYYY>-<M>-<D>

Is HTML mein har page ki image seedha <img> tag mein hoti hai:

    https://e.dailyparliamenttimes.com/media/<edition>/epaper/<YYYY>/<MM>/<DD>/<page_number>.jpg

(Note: image folder ki date kabhi kabhi "dt=" wali date se 1 din peechay
hoti hai -- ye normal hai, site khud aisi hi save karti hai. Script
seedha jo bhi asal URL milta hai wahi use karti hai, koi date guess
nahi karti.)

Requirements:
    pip install requests pillow

Usage:
    python parliamenttimes_epaper_downloader.py
    python parliamenttimes_epaper_downloader.py --editions Islamabad Quetta
    python parliamenttimes_epaper_downloader.py --outdir "C:/ParliamentTimesPDFs"
    python parliamenttimes_epaper_downloader.py --keep-images

Agar koi edition fail ho:
    python parliamenttimes_epaper_downloader.py --debug-dump islamabad:2026-7-16
    Ye "parliamenttimes_debug_page.html" bana degi -- wo file bhej dein
    taake pattern turant fix kiya ja sake.

Automatic daily run:
-----------------------------------------------------------------
  Windows (Task Scheduler): Daily trigger, program "python", arguments
  "C:\\path\\parliamenttimes_epaper_downloader.py"

  Linux/Mac (cron) -- roz subah 8:00 baje:
    0 8 * * * /usr/bin/python3 /path/parliamenttimes_epaper_downloader.py
"""

import argparse
import concurrent.futures
import io
import os
import re
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


BASE = "https://e.dailyparliamenttimes.com"

EDITIONS = {
    "Islamabad": "islamabad",
    "Quetta": "quetta",
    "AJK": "muzaffarabad",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ur;q=0.8",
    "Referer": BASE + "/",
    "Connection": "keep-alive",
}

HTML_RETRIES = 4
IMAGE_RETRIES = 5
RETRY_SLEEP = 1.5
REQUEST_TIMEOUT = 40
THREADS_PER_EDITION = 4

PKT = timezone(timedelta(hours=5))


def unescape_slashes(text):
    r"""JSON blobs mein "https:\/\/..." jaisi escaped slashes aam hain."""
    return text.replace('\\/', '/')


def today_dt_param():
    """Site ko 'YYYY-M-D' format chahiye (bina leading zero ke)."""
    now = datetime.now(PKT)
    return f"{now.year}-{now.month}-{now.day}"


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


def http_get(session, url):
    last_err = None
    for attempt in range(1, HTML_RETRIES + 1):
        try:
            r = session.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
            if r.status_code == 200 and r.text:
                return r
            last_err = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last_err = str(e)
        time.sleep(RETRY_SLEEP * attempt)
    log(f"    FAILED after {HTML_RETRIES} tries: {url}  ({last_err})")
    return None


def get_page_image_urls(session, slug, dt_param):
    """
    Edition ki poori din-page (ek hi fetch) se saare page image URLs
    nikaal ke, page number ke hisaab se sorted list return karta hai.
    NOTE: Kabhi kabhi filename mein number ke baad ek letter bhi hota
    hai (jaise "1q.jpg" Quetta mein, ya "4m.jpg" AJK mein) -- ye
    seedha nahi ignore karte, poora filename hi rakhte hain, sirf
    ordering ke liye number wala hissa nikaalte hain.
    """
    url = f"{BASE}/e/{slug}/?dt={dt_param}"
    r = http_get(session, url)
    if r is None:
        return None

    pattern = re.compile(
        r'/media/' + re.escape(slug) + r'/epaper/(\d{4})/(\d{2})/(\d{2})/(\d+[a-zA-Z]?)\.jpg',
        re.IGNORECASE,
    )

    seen = {}
    for text in (r.text, unescape_slashes(r.text)):
        for m in pattern.finditer(text):
            year, month, day, filename = m.groups()
            page_num = int(re.match(r'\d+', filename).group())
            seen[page_num] = f"{BASE}/media/{slug}/epaper/{year}/{month}/{day}/{filename}.jpg"

    if not seen:
        return None

    ordered = [seen[k] for k in sorted(seen.keys())]
    return ordered


def download_and_verify_image(session, url):
    last_err = None
    for attempt in range(1, IMAGE_RETRIES + 1):
        try:
            r = session.get(url, timeout=REQUEST_TIMEOUT, stream=True)
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
                        return content
                    except Exception as e:
                        last_err = f"corrupt/truncated image ({e})"
        except requests.RequestException as e:
            last_err = str(e)

        time.sleep(RETRY_SLEEP * attempt)

    log(f"    FAILED after {IMAGE_RETRIES} tries: {url}  ({last_err})")
    return None


def process_edition(edition_name, slug, dt_param, outdir, keep_images):
    log(f"==> {edition_name} (edition={slug}): page images nikaali ja rahi hain...")
    session = make_session()

    image_urls = get_page_image_urls(session, slug, dt_param)
    if not image_urls:
        log(f"==> {edition_name}: koi image URL nahi mila (edition FAIL). "
            f"--debug-dump {slug}:{dt_param} chala kar dekhein.")
        return None

    log(f"==> {edition_name}: {len(image_urls)} pages mile.")

    def worker(idx_url):
        idx, img_url = idx_url
        content = download_and_verify_image(session, img_url)
        if content is None:
            log(f"    [{edition_name}] page {idx+1} (id={idx}): download FAIL (skip)")
        else:
            log(f"    [{edition_name}] page {idx+1}/{len(image_urls)}: OK ({len(content)} bytes)")
        return idx, content

    downloaded = [None] * len(image_urls)
    with concurrent.futures.ThreadPoolExecutor(max_workers=THREADS_PER_EDITION) as ex:
        for idx, content in ex.map(worker, enumerate(image_urls)):
            downloaded[idx] = content

    pil_images = []
    if keep_images:
        tag = f"{edition_name}_{dt_param.replace('-', '')}"
        tmp_dir = os.path.join(outdir, "_raw", tag)
        os.makedirs(tmp_dir, exist_ok=True)

    for idx, content in enumerate(downloaded):
        if content is None:
            continue
        try:
            im = Image.open(io.BytesIO(content))
            im.load()
            im = im.convert("RGB")
        except Exception as e:
            log(f"    [{edition_name}] page {idx+1}: open error, skip: {e}")
            continue
        pil_images.append(im)
        if keep_images:
            im.save(os.path.join(tmp_dir, f"{idx+1:02d}.jpg"), quality=95)

    if not pil_images:
        log(f"==> {edition_name}: koi bhi page successfully download nahi hua, PDF skip.")
        return None

    os.makedirs(outdir, exist_ok=True)
    pretty_date = datetime.now(PKT).strftime("%d%B")

    pdf_name = f"ParliamentTimes {edition_name} {pretty_date}.pdf"
    pdf_path = os.path.join(outdir, pdf_name)

    first, rest = pil_images[0], pil_images[1:]
    first.save(pdf_path, save_all=True, append_images=rest)
    log(f"==> {edition_name}: PDF ban gayi -> {pdf_path}  ({len(pil_images)}/{len(image_urls)} pages)")
    if len(pil_images) < len(image_urls):
        log(f"    NOTE: {len(image_urls) - len(pil_images)} page(s) download nahi ho sake.")
    return pdf_path


def main():
    parser = argparse.ArgumentParser(description="Daily Parliament Times Epaper auto downloader -> PDF")
    parser.add_argument(
        "--editions",
        nargs="+",
        choices=list(EDITIONS.keys()),
        default=None,
        help="Sirf in editions ko download karein (default: sab 3).",
    )
    parser.add_argument(
        "--outdir",
        default=os.path.join(os.getcwd(), "ParliamentTimes_Epaper_PDFs"),
        help="PDF output folder",
    )
    parser.add_argument(
        "--keep-images",
        action="store_true",
        help="Har page ki alag JPG bhi rakhein (_raw folder mein).",
    )
    parser.add_argument(
        "--debug-dump",
        metavar="SLUG:YYYY-M-D",
        default=None,
        help=(
            "Debug mode: sirf ek edition ki raw HTML "
            "'parliamenttimes_debug_page.html' mein save kar dega. "
            "Misaal: --debug-dump islamabad:2026-7-16"
        ),
    )
    args = parser.parse_args()

    if args.debug_dump:
        try:
            slug, dt_param = args.debug_dump.split(":", 1)
        except ValueError:
            sys.exit("--debug-dump ka format SLUG:YYYY-M-D hona chahiye, misaal: islamabad:2026-7-16")
        session = make_session()
        url = f"{BASE}/e/{slug}/?dt={dt_param}"
        r = http_get(session, url)
        if r is None:
            sys.exit(f"Page fetch nahi ho saka: {url}")
        out_path = "parliamenttimes_debug_page.html"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(r.text)
        found = get_page_image_urls(session, slug, dt_param)
        log(f"Raw HTML save ho gayi: {out_path} ({len(r.text)} chars)")
        log(f"Extractor ka result: {found or 'KUCH NAHI MILA'}")
        return

    os.makedirs(args.outdir, exist_ok=True)
    log(f"Output folder: {args.outdir}")
    dt_param = today_dt_param()
    log(f"Aaj ki tareekh (PKT, dt param): {dt_param}")

    chosen = args.editions or list(EDITIONS.keys())
    log(f"Editions ({len(chosen)}): {', '.join(chosen)}")

    results = {}
    for name in chosen:
        slug = EDITIONS[name]
        try:
            path = process_edition(name, slug, dt_param, args.outdir, args.keep_images)
            results[name] = path
        except Exception as e:
            log(f"==> {name}: UNEXPECTED ERROR -> {e}")
            results[name] = None

    log("")
    log("===================== SUMMARY =====================")
    ok = 0
    for name, path in results.items():
        status = path if path else "FAILED"
        log(f"{name:12s} -> {status}")
        if path:
            ok += 1
    log(f"Total: {ok}/{len(results)} editions successful.")
    log("=====================================================")


if __name__ == "__main__":
    main()
