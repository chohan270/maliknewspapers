#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daily Country News Epaper (dailycountrynews.com/epaper) Auto Downloader
=========================================================================
Editions: Islamabad, AJK, Peshawar, Karachi (confirmed se site pe
maujood), + Lahore, Gilgit Baltistan, Magazine (site ke menu mein naam
hain, lekin inke exact URL "slug" 100% confirm nahi ho saka -- agar ye
teen fail hon to neeche "Agar koi edition fail ho" wala hissa parhein).

SITE PATTERN (scrape se maloom hua):
-------------------------------------
1) https://dailycountrynews.com/epaper/  -> har edition ka apna "slug":
      Islamabad -> islamabad
      AJK       -> ajk
      Peshawar  -> peshawar
      Karachi   -> karachi
      Magazine  -> magzine   (site khud isko "magzine" likhta hai)
      (Lahore aur Gilgit Baltistan ke slug guess kiye gaye hain:
       "lahore" aur "gilgit" -- agar galat hue to script khud hi
       "0 pages" bata degi aur wo edition skip ho jayega)

2) https://dailycountrynews.com/epaper/page.php?id=1&edition=<SLUG>&dt=<DD-MM-YYYY>
   -> is HTML mein us din ke saare pages ke links milte hain:
        page.php?id=<N>&edition=<SLUG>&dt=<DATE>

3) NOTE: Is site ka page-viewer bhi image ko table/JS ke andar
   dikhata hai (seedha readable <img> tag nahi milta -- Khabrain jaisi
   situation). Isi liye script kai tareeqon (og:image, "-full.jpg"
   pattern, JSON blob, maphilighted img tag) se image dhoondti hai.
   Agar pehli dafa kisi edition ka "image URL nahi mili" aaye, to
   --debug-dump wala option chalayein (neeche dekhein) aur file bhej
   dein -- turant regex fix kar diya jayega, bilkul jaise Khabrain
   mein hua tha.

Requirements:
    pip install requests pillow

Usage:
    python countrynews_epaper_downloader.py
    python countrynews_epaper_downloader.py --editions Islamabad Karachi
    python countrynews_epaper_downloader.py --outdir "C:/CountryNewsPDFs"
    python countrynews_epaper_downloader.py --keep-images

Agar koi edition fail ho (0 pages ya "image URL nahi mili"):
    python countrynews_epaper_downloader.py --debug-dump islamabad:1:16-07-2026
    (islamabad=edition slug, 1=page id, 16-07-2026=date -- error log
    se lein). Ye "countrynews_debug_page.html" bana degi -- wo file
    bhej dein taake regex 100% theek kiya ja sake.

Automatic daily run:
-----------------------------------------------------------------
  Windows (Task Scheduler): Daily trigger, program "python", arguments
  "C:\\path\\countrynews_epaper_downloader.py"

  Linux/Mac (cron) -- roz subah 8:00 baje:
    0 8 * * * /usr/bin/python3 /path/countrynews_epaper_downloader.py
"""

import argparse
import concurrent.futures
import io
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

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


BASE = "https://dailycountrynews.com/epaper"

# Confirmed slugs (site ki apni HTML se) + best-guess slugs (comment
# mein bataya gaya hai). Agar guess wale kaam na karein to
# --editions flag se sirf confirmed wale chala sakte hain.
EDITIONS = {
    "Islamabad": "islamabad",       # confirmed
    "AJK": "ajk",                   # confirmed
    "Peshawar": "peshawar",         # confirmed
    "Karachi": "karachi",           # confirmed
    "Lahore": "lahore",             # best-guess
    "Gilgit_Baltistan": "gilgit",   # best-guess
    "Magazine": "magzine",          # confirmed slug spelling
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

PKT = timezone(timedelta(hours=5))

# Multi-strategy image patterns (site ka exact tareeqa 100% maloom nahi,
# isi liye kai fallback patterns rakhe gaye hain):
# CONFIRMED pattern (asal HTML se): full-size page ki image hamesha
# class='map' wale <img> tag mein hoti hai, src bina quotes ke hota hai:
#   <img src=../assets/islamabad/16-07-2026/1.jpg ... class='map' ...>
# Pattern: ../assets/<edition>/<DD-MM-YYYY>/<page_number>.jpg
MAP_IMG_RE = re.compile(
    r'<img\s+src=([^\s>"\']+)[^>]*class=["\']map["\']',
    re.IGNORECASE,
)
MAPHILIGHTED_IMG_RE = re.compile(
    r'<img[^>]*class=["\']maphilighted["\'][^>]*src=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
FULL_IMG_RE = re.compile(
    r'(?:https?://dailycountrynews\.com)?/?epaper/(?:issues|uploads|images|pages)/[^"\'\s]+?\.(?:jpg|jpeg|png)',
    re.IGNORECASE,
)
JSON_IMAGE_KEY_RE = re.compile(
    r'["\'](?:image|img|page_image|src|url|file|path)["\']\s*:\s*["\']([^"\']+\.(?:jpg|jpeg|png))["\']',
    re.IGNORECASE,
)
OG_IMAGE_RE = re.compile(
    r'property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
ANY_JPG_IN_EPAPER_RE = re.compile(
    r'(?:https?:)?(?:\\?/){0,2}[^"\'\s]*?epaper[^"\'\s]*?\.(?:jpg|jpeg|png)',
    re.IGNORECASE,
)
PAGE_LINK_RE_TEMPLATE = r'page\.php\?id=(\d+)&(?:amp;)?edition={slug}&(?:amp;)?dt=(\d{{2}}-\d{{2}}-\d{{4}})'


def unescape_slashes(text):
    r"""JSON blobs mein "https:\/\/..." jaisi escaped slashes aam hain."""
    return text.replace('\\/', '/')


def make_absolute(url, page_url):
    return urljoin(page_url, url)


def today_pkt_str():
    return datetime.now(PKT).strftime("%d-%m-%Y")


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


def get_page_list(session, slug, date_str):
    url = f"{BASE}/page.php?id=1&edition={slug}&dt={date_str}"
    r = http_get(session, url)
    if r is None:
        return None

    pattern = re.compile(PAGE_LINK_RE_TEMPLATE.format(slug=re.escape(slug)), re.IGNORECASE)
    pairs = pattern.findall(r.text)
    seen = set()
    pages = []
    for pid, dt in pairs:
        if pid not in seen:
            seen.add(pid)
            pages.append((int(pid), dt))
    pages.sort(key=lambda x: x[0])

    if not pages:
        # Kam az kam page 1 to zaroor hai (agar aaj edition chapi hai)
        return [(1, date_str)]
    return pages


def extract_full_image_url(html_text, page_url):
    for text in (html_text, unescape_slashes(html_text)):
        m = MAP_IMG_RE.search(text)
        if m:
            return make_absolute(m.group(1), page_url)

        m = MAPHILIGHTED_IMG_RE.search(text)
        if m:
            return make_absolute(m.group(1), page_url)

        m = FULL_IMG_RE.search(text)
        if m:
            return make_absolute(m.group(0), page_url)

        m = JSON_IMAGE_KEY_RE.search(text)
        if m:
            return make_absolute(m.group(1), page_url)

        m = OG_IMAGE_RE.search(text)
        if m:
            url = m.group(1)
            if url.lower().endswith((".jpg", ".jpeg", ".png")):
                return make_absolute(url, page_url)

        m = ANY_JPG_IN_EPAPER_RE.search(text)
        if m:
            return make_absolute(m.group(0), page_url)

    return None


def get_page_image_url(session, slug, page_id, date_str):
    url = f"{BASE}/page.php?id={page_id}&edition={slug}&dt={date_str}"
    for attempt in range(1, PAGE_ID_RETRIES + 1):
        r = http_get(session, url)
        if r is None:
            time.sleep(RETRY_SLEEP * attempt)
            continue
        img_url = extract_full_image_url(r.text, url)
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


def process_edition(edition_name, slug, date_str, outdir, keep_images):
    log(f"==> {edition_name} (edition={slug}): page list nikaali ja rahi hai...")
    session = make_session()

    pages = get_page_list(session, slug, date_str)
    if not pages:
        log(f"==> {edition_name}: page list scrape se nahi mili (edition FAIL). "
            f"Slug '{slug}' galat ho sakta hai.")
        return None

    log(f"==> {edition_name}: {len(pages)} pages mile.")

    def worker(idx_page):
        idx, (pid, dt) = idx_page
        img_url = get_page_image_url(session, slug, pid, dt)
        if img_url is None:
            log(f"    [{edition_name}] page {idx+1} (id={pid}): image URL nahi mili (skip)")
            return idx, None
        content = download_and_verify_image(session, img_url)
        if content is None:
            log(f"    [{edition_name}] page {idx+1} (id={pid}): download FAIL (skip)")
        else:
            log(f"    [{edition_name}] page {idx+1}/{len(pages)}: OK ({len(content)} bytes)")
        return idx, content

    downloaded = [None] * len(pages)
    with concurrent.futures.ThreadPoolExecutor(max_workers=THREADS_PER_EDITION) as ex:
        for idx, content in ex.map(worker, enumerate(pages)):
            downloaded[idx] = content

    pil_images = []
    if keep_images:
        tag = f"{edition_name}_{date_str.replace('-', '')}"
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
        pretty_date = datetime.strptime(date_str, "%d-%m-%Y").strftime("%d%B")
    except ValueError:
        pretty_date = date_str

    pdf_name = f"CountryNews {edition_name.replace('_', ' ')} {pretty_date}.pdf"
    pdf_path = os.path.join(outdir, pdf_name)

    first, rest = pil_images[0], pil_images[1:]
    first.save(pdf_path, save_all=True, append_images=rest)
    log(f"==> {edition_name}: PDF ban gayi -> {pdf_path}  ({len(pil_images)}/{len(pages)} pages)")
    if len(pil_images) < len(pages):
        log(f"    NOTE: {len(pages) - len(pil_images)} page(s) is edition mein download nahi ho sake.")
    return pdf_path


def main():
    parser = argparse.ArgumentParser(description="Daily Country News Epaper auto downloader -> PDF")
    parser.add_argument(
        "--editions",
        nargs="+",
        choices=list(EDITIONS.keys()),
        default=None,
        help="Sirf in editions ko download karein (default: sab).",
    )
    parser.add_argument(
        "--outdir",
        default=os.path.join(os.getcwd(), "CountryNews_Epaper_PDFs"),
        help="PDF output folder",
    )
    parser.add_argument(
        "--keep-images",
        action="store_true",
        help="Har page ki alag JPG bhi rakhein (_raw folder mein).",
    )
    parser.add_argument(
        "--debug-dump",
        metavar="SLUG:PAGE_ID:DD-MM-YYYY",
        default=None,
        help=(
            "Debug mode: sirf ek page ki raw HTML "
            "'countrynews_debug_page.html' mein save kar dega. "
            "Misaal: --debug-dump islamabad:1:16-07-2026"
        ),
    )
    args = parser.parse_args()

    if args.debug_dump:
        try:
            slug, pid_str, date_str = args.debug_dump.split(":")
            pid = int(pid_str)
        except ValueError:
            sys.exit("--debug-dump ka format SLUG:PAGE_ID:DD-MM-YYYY hona chahiye, misaal: islamabad:1:16-07-2026")
        session = make_session()
        url = f"{BASE}/page.php?id={pid}&edition={slug}&dt={date_str}"
        r = http_get(session, url)
        if r is None:
            sys.exit(f"Page fetch nahi ho saka: {url}")
        out_path = "countrynews_debug_page.html"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(r.text)
        found = extract_full_image_url(r.text, url)
        log(f"Raw HTML save ho gayi: {out_path} ({len(r.text)} chars)")
        log(f"Extractor ka result: {found or 'KUCH NAHI MILA'}")
        return

    os.makedirs(args.outdir, exist_ok=True)
    log(f"Output folder: {args.outdir}")
    date_str = today_pkt_str()
    log(f"Aaj ki tareekh (PKT, DD-MM-YYYY): {date_str}")

    chosen = args.editions or list(EDITIONS.keys())
    log(f"Editions ({len(chosen)}): {', '.join(chosen)}")

    results = {}
    for name in chosen:
        slug = EDITIONS[name]
        try:
            path = process_edition(name, slug, date_str, args.outdir, args.keep_images)
            results[name] = path
        except Exception as e:
            log(f"==> {name}: UNEXPECTED ERROR -> {e}")
            results[name] = None

    log("")
    log("===================== SUMMARY =====================")
    ok = 0
    for name, path in results.items():
        status = path if path else "FAILED"
        log(f"{name:18s} -> {status}")
        if path:
            ok += 1
    log(f"Total: {ok}/{len(results)} editions successful.")
    log("=====================================================")


if __name__ == "__main__":
    main()
