#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pakistan Observer Epaper (epaper.pakobserver.net) Auto Downloader
=====================================================================
Cities: Islamabad, Lahore, Karachi, Peshawar.

SITE PATTERN (scrape se maloom hua):
-------------------------------------
1) https://epaper.pakobserver.net/  -> har city ka "station_id":
      Islamabad=1, Lahore=2, Karachi=3, Peshawar=5

2) https://epaper.pakobserver.net/pages.php?station_id=<ID>
   -> is HTML mein "Pages" list milti hai jisme har page ka apna link
      hota hai (page_id + date):
        pages.php?station_id=<ID>&page_id=<PAGE_ID>&date=<YYYY-MM-DD>

3) Har page_id wale URL ki raw HTML mein seedha ek <img> tag hota hai:
        <img src="https://epaper.pakobserver.net/issues/YYYY/YYYY-MM-DD/<digits>-full.jpg">
   (Khabrain jaisi JS/AJAX complexity yahan NAHI hai -- image seedha
   HTML mein milti hai, isi liye ye zyada simple/reliable hai.)

4) Agar kisi page ki image na milay to sirf wo page skip hota hai,
   baqi pages se PDF phir bhi ban jaati hai.

Requirements:
    pip install requests pillow

Usage:
    python pakobserver_epaper_downloader.py
    python pakobserver_epaper_downloader.py --editions Lahore Karachi
    python pakobserver_epaper_downloader.py --outdir "C:/PakObserverPDFs"
    python pakobserver_epaper_downloader.py --keep-images

Debug (agar koi city fail ho):
    python pakobserver_epaper_downloader.py --debug-dump 2:45037:2026-07-03
    (2=station_id, 45037=page_id, 2026-07-03=date -- teeno error log se
    lein). Ye "pakobserver_debug_page.html" bana degi jo dekh kar
    regex fix kiya ja sakta hai.

Automatic daily run:
-----------------------------------------------------------------
  Windows (Task Scheduler): Daily trigger, program "python", arguments
  "C:\\path\\pakobserver_epaper_downloader.py"

  Linux/Mac (cron) -- roz subah 8:00 baje:
    0 8 * * * /usr/bin/python3 /path/pakobserver_epaper_downloader.py
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


BASE = "https://epaper.pakobserver.net"

EDITIONS = {
    "Islamabad": 1,
    "Lahore": 2,
    "Karachi": 3,
    "Peshawar": 5,
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
PAGE_ID_RETRIES = 3
RETRY_SLEEP = 1.5
REQUEST_TIMEOUT = 40
THREADS_PER_EDITION = 4

PKT = timezone(timedelta(hours=5))  # Pakistan Standard Time

# Confirmed pattern:
#   https://epaper.pakobserver.net/issues/YYYY/YYYY-MM-DD/<digits>-full.jpg
FULL_IMG_RE = re.compile(
    r'(?:https?://epaper\.pakobserver\.net)?/?issues/\d{4}/\d{4}-\d{2}-\d{2}/\d+-full\.jpg',
    re.IGNORECASE,
)
PAGE_ID_LINK_RE = re.compile(
    r'station_id=(\d+)&(?:amp;)?page_id=(\d+)&(?:amp;)?date=(\d{4}-\d{2}-\d{2})',
    re.IGNORECASE,
)


def unescape_slashes(text):
    r"""JSON blobs mein "https:\/\/..." jaisi escaped slashes aam hain."""
    return text.replace('\\/', '/')


def make_absolute(url):
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return BASE + url
    return BASE + "/" + url


def today_pkt_str():
    return datetime.now(PKT).strftime("%Y-%m-%d")


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


def http_get(session, url, extra_headers=None):
    last_err = None
    hdrs = dict(HEADERS)
    if extra_headers:
        hdrs.update(extra_headers)
    for attempt in range(1, HTML_RETRIES + 1):
        try:
            r = session.get(url, timeout=REQUEST_TIMEOUT, headers=hdrs)
            if r.status_code == 200 and r.text:
                return r
            last_err = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last_err = str(e)
        time.sleep(RETRY_SLEEP * attempt)
    log(f"    FAILED after {HTML_RETRIES} tries: {url}  ({last_err})")
    return None


def get_page_list(session, station_id):
    """
    Station ki base URL se aaj ke saare (page_number, page_id, date)
    nikaalta hai. Returns ordered list of (page_id, date) tuples, ya
    None agar list na milay.
    """
    url = f"{BASE}/pages.php?station_id={station_id}"
    r = http_get(session, url)
    if r is None:
        return None

    triples = PAGE_ID_LINK_RE.findall(r.text)
    seen = set()
    pages = []
    for sid, pid, date in triples:
        if int(sid) == station_id and pid not in seen:
            seen.add(pid)
            pages.append((int(pid), date))

    return pages or None


def extract_full_image_url(html_text):
    for text in (html_text, unescape_slashes(html_text)):
        m = FULL_IMG_RE.search(text)
        if m:
            return make_absolute(m.group(0))
    return None


def get_page_image_url(session, station_id, page_id, date):
    url = f"{BASE}/pages.php?station_id={station_id}&page_id={page_id}&date={date}"
    for attempt in range(1, PAGE_ID_RETRIES + 1):
        r = http_get(session, url)
        if r is None:
            time.sleep(RETRY_SLEEP * attempt)
            continue
        img_url = extract_full_image_url(r.text)
        if img_url:
            return img_url
        time.sleep(RETRY_SLEEP * attempt)
    return None


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


def process_edition(edition_name, station_id, outdir, keep_images):
    log(f"==> {edition_name} (station_id={station_id}): page list nikaali ja rahi hai...")
    session = make_session()

    pages = get_page_list(session, station_id)
    if not pages:
        log(f"==> {edition_name}: page list scrape se nahi mili (edition FAIL). "
            f"Site ka HTML structure badal gaya ho sakta hai -- "
            f"--debug-dump {station_id}:<page_id>:<date> chala kar dekhein.")
        return None

    log(f"==> {edition_name}: {len(pages)} pages mile ({pages[0][1]}).")

    def worker(idx_page):
        idx, (pid, date) = idx_page
        img_url = get_page_image_url(session, station_id, pid, date)
        if img_url is None:
            log(f"    [{edition_name}] page {idx+1} (page_id={pid}): image URL nahi mili (skip)")
            return idx, None
        content = download_and_verify_image(session, img_url)
        if content is None:
            log(f"    [{edition_name}] page {idx+1} (page_id={pid}): download FAIL (skip)")
        else:
            log(f"    [{edition_name}] page {idx+1}/{len(pages)}: OK ({len(content)} bytes)")
        return idx, content

    downloaded = [None] * len(pages)
    with concurrent.futures.ThreadPoolExecutor(max_workers=THREADS_PER_EDITION) as ex:
        for idx, content in ex.map(worker, enumerate(pages)):
            downloaded[idx] = content

    pil_images = []
    if keep_images:
        tag = f"{edition_name}_{pages[0][1]}"
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
    try:
        edition_date = datetime.strptime(pages[0][1], "%Y-%m-%d")
        pretty_date = edition_date.strftime("%d%B")
    except ValueError:
        pretty_date = pages[0][1]

    pdf_name = f"PakObserver {edition_name} {pretty_date}.pdf"
    pdf_path = os.path.join(outdir, pdf_name)

    first, rest = pil_images[0], pil_images[1:]
    first.save(pdf_path, save_all=True, append_images=rest)
    log(f"==> {edition_name}: PDF ban gayi -> {pdf_path}  ({len(pil_images)}/{len(pages)} pages)")
    if len(pil_images) < len(pages):
        log(f"    NOTE: {len(pages) - len(pil_images)} page(s) is edition mein download nahi ho sake.")
    return pdf_path


def main():
    parser = argparse.ArgumentParser(description="Pakistan Observer Epaper auto downloader -> PDF")
    parser.add_argument(
        "--editions",
        nargs="+",
        choices=list(EDITIONS.keys()),
        default=None,
        help="Sirf in editions ko download karein (default: sab 4).",
    )
    parser.add_argument(
        "--outdir",
        default=os.path.join(os.getcwd(), "PakObserver_Epaper_PDFs"),
        help="PDF output folder",
    )
    parser.add_argument(
        "--keep-images",
        action="store_true",
        help="Har page ki alag JPG bhi rakhein (_raw folder mein).",
    )
    parser.add_argument(
        "--debug-dump",
        metavar="STATION_ID:PAGE_ID:DATE",
        default=None,
        help=(
            "Debug mode: sirf ek page ki raw HTML "
            "'pakobserver_debug_page.html' mein save kar dega. "
            "Misaal: --debug-dump 2:45037:2026-07-03"
        ),
    )
    args = parser.parse_args()

    if args.debug_dump:
        try:
            sid_str, pid_str, date_str = args.debug_dump.split(":")
            sid, pid = int(sid_str), int(pid_str)
        except ValueError:
            sys.exit("--debug-dump ka format STATION_ID:PAGE_ID:DATE hona chahiye, misaal: 2:45037:2026-07-03")
        session = make_session()
        url = f"{BASE}/pages.php?station_id={sid}&page_id={pid}&date={date_str}"
        r = http_get(session, url)
        if r is None:
            sys.exit(f"Page fetch nahi ho saka: {url}")
        out_path = "pakobserver_debug_page.html"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(r.text)
        found = extract_full_image_url(r.text)
        log(f"Raw HTML save ho gayi: {out_path} ({len(r.text)} chars)")
        log(f"Extractor ka result: {found or 'KUCH NAHI MILA'}")
        return

    os.makedirs(args.outdir, exist_ok=True)
    log(f"Output folder: {args.outdir}")
    log(f"Aaj ki tareekh (PKT): {today_pkt_str()}")

    chosen = args.editions or list(EDITIONS.keys())
    log(f"Editions ({len(chosen)}): {', '.join(chosen)}")

    results = {}
    for name in chosen:
        station_id = EDITIONS[name]
        try:
            path = process_edition(name, station_id, args.outdir, args.keep_images)
            results[name] = path
        except Exception as e:
            log(f"==> {name}: UNEXPECTED ERROR -> {e}")
            results[name] = None

    log("")
    log("===================== SUMMARY =====================")
    ok = 0
    for name, path in results.items():
        status = path if path else "FAILED"
        log(f"{name:16s} -> {status}")
        if path:
            ok += 1
    log(f"Total: {ok}/{len(results)} editions successful.")
    log("=====================================================")


if __name__ == "__main__":
    main()
