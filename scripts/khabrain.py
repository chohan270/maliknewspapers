#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daily Khabrain Epaper (epaper.dailykhabrain.com.pk) Auto Downloader
=====================================================================
Cities: Lahore, Islamabad, Bahawalpur, Karachi, Multan, Muzaffarabad,
Peshawar, aur Naya Akhbar (Lahore).

Sunday Magazine: Agar aaj Sunday hai to "Sunday Magazine" (station_id=11)
apne aap ek ALAG PDF mein download ho jati hai. Baqi dinon mein ye
station skip ho jata hai (kyunke magazine hafte mein sirf ek din chapti
hai) -- isi liye "alag se" aur "sirf Sunday" wali setting neeche
SUNDAY_MAGAZINE_STATION mein already built-in hai, kuch aur karne ki
zaroorat nahi.

SITE PATTERN (scrape se maloom hua):
-------------------------------------
1) https://epaper.dailykhabrain.com.pk/  -> har city ka "station_id":
      Lahore=7, Islamabad=13, Bahawalpur=18, Karachi=12, Multan=9,
      Muzaffarabad=8, Peshawar=17, Naya Akhbar=10, Sunday Magazine=11

2) https://epaper.dailykhabrain.com.pk/epaper?station_id=<ID>
   -> is HTML ke andar "صفحات" (Pages) list milti hai jisme har page
      ka apna link hota hai:
        .../epaper?station_id=<ID>&page_id=<PAGE_ID>
      Yehi se hume maloom hota hai ke aaj us city ke kitne pages hain.

3) Har page_id wale URL ko fetch karke us page ki asli tasveer (JPG)
   dhoondi jaati hai. Ye site JS/AJAX se image load karti hai, is liye
   script kai tareeqon (og:image tag, "-full.jpg" pattern, JSON blob)
   se image URL dhoondti hai -- jo bhi pehlay mil jaye wahi use hota hai.
   Full-resolution image hamesha "...-full.jpg" pe khatam hoti hai.

4) Agar kisi page ki image na milay to sirf wo page skip hota hai,
   baqi pages se PDF phir bhi ban jaati hai (jaisa Express/NaiBaat
   scripts mein hota hai).

Requirements:
    pip install requests pillow beautifulsoup4

Usage:
    python khabrain_epaper_downloader.py
    python khabrain_epaper_downloader.py --editions Lahore Karachi
    python khabrain_epaper_downloader.py --outdir "C:/KhabrainPDFs"
    python khabrain_epaper_downloader.py --keep-images

Agar koi edition "image URL nahi mili" bole (site ka JS-loading tareeqa
badal gaya ho):
    python khabrain_epaper_downloader.py --debug-dump 7:261596
    (7 = station_id, 261596 = koi bhi page_id jo error mein dikha ho)
    Ye ek "khabrain_debug_page.html" file bana degi -- wo file bhej
    dein taake regex turant thk kiya ja sake.

Automatic daily run (taake aap ko roz khud chalana na paray):
-----------------------------------------------------------------
  Windows (Task Scheduler):
    1) Task Scheduler khol kar "Create Basic Task" per click karein.
    2) Trigger = "Daily", waqt aap ki marzi (e.g. subah 8:00 AM taake
       us waqt tak edition upload ho chuka ho).
    3) Action = "Start a Program":
         Program:  python
         Arguments: "C:\\path\\khabrain_epaper_downloader.py"
    4) Sunday Magazine khud detect ho jayegi (koi alag task nahi
       chahiye) -- lekin agar chahen to alag se HAR SUNDAY 9:00 AM
       wala ek dusra task bhi bana sakte hain jo isi script ko
       "--editions Sunday_Magazine" ke saath chalaye.

  Linux/Mac (cron) -- roz subah 8:00 baje:
    0 8 * * * /usr/bin/python3 /path/khabrain_epaper_downloader.py
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


BASE = "https://epaper.dailykhabrain.com.pk"

# City name -> station_id (site se scrape kiya gaya)
EDITIONS = {
    "Lahore": 7,
    "Islamabad": 13,
    "Bahawalpur": 18,
    "Karachi": 12,
    "Multan": 9,
    "Muzaffarabad": 8,
    "Peshawar": 17,
    "Naya_Akhbar": 10,
}

# Sunday Magazine -- sirf Sunday ko chalega, alag PDF banegi
SUNDAY_MAGAZINE_NAME = "Sunday_Magazine"
SUNDAY_MAGAZINE_STATION = 11

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
MAX_PAGES_FALLBACK = 30  # agar page-list scrape fail ho jaye to itne page_id tak try karein

PKT = timezone(timedelta(hours=5))  # Pakistan Standard Time

# Asal, confirmed pattern: site ye image is tarah deti hai (bina
# leading slash ke, class="maphilighted" wale <img> tag mein):
#   <img class="maphilighted" src="issues/2026-07-12/1783834221-full.jpg" usemap="#dynmap"/>
MAPHILIGHTED_IMG_RE = re.compile(
    r'<img[^>]*class=["\']maphilighted["\'][^>]*src=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
# Full-size image hamesha isi pattern se milti hai (leading slash ke
# bina bhi ho sakta hai, is liye woh optional rakha hai):
#   (https://epaper.dailykhabrain.com.pk/)?issues/YYYY-MM-DD/<digits>-full.jpg
FULL_IMG_RE = re.compile(
    r'(?:https?://epaper\.dailykhabrain\.com\.pk/)?issues/\d{4}-\d{2}-\d{2}/\d+-full\.jpg',
    re.IGNORECASE,
)
# Kisi bhi JSON jaisi key (image / img / page_image / src / url waghera)
# ke andar koi bhi .jpg/.jpeg/.png link -- broad fallback.
JSON_IMAGE_KEY_RE = re.compile(
    r'["\'](?:image|img|page_image|src|url|file|path)["\']\s*:\s*["\']([^"\']+\.(?:jpg|jpeg|png))["\']',
    re.IGNORECASE,
)
OG_IMAGE_RE = re.compile(
    r'property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
PAGE_ID_LINK_RE = re.compile(
    r'station_id=(\d+)&(?:amp;)?page_id=(\d+)',
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


def is_today_sunday_pkt():
    return datetime.now(PKT).weekday() == 6  # Monday=0 ... Sunday=6


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


def get_page_id_list(session, station_id):
    """
    Station ki base URL se aaj ke saare page_id nikaalta hai
    (صفحات list se). Returns ordered list of page_id ints (page1 first).
    Agar list na milay to None return karta hai (fallback trigger karne
    ke liye).
    """
    url = f"{BASE}/epaper?station_id={station_id}"
    r = http_get(session, url)
    if r is None:
        return None

    pairs = PAGE_ID_LINK_RE.findall(r.text)
    # sirf isi station ke page_id chahiye, tarteeb (order) preserve karte
    # hue, duplicates hataate hue
    seen = set()
    page_ids = []
    for sid, pid in pairs:
        if int(sid) == station_id and pid not in seen:
            seen.add(pid)
            page_ids.append(int(pid))

    return page_ids or None


def extract_full_image_url(html_text):
    """
    Confirmed pattern pehle try karta hai (class="maphilighted" wala
    <img> tag), phir baaki fallback patterns. Relative src ("issues/...")
    ko sahi tarah absolute URL mein convert kar deta hai.
    """
    for text in (html_text, unescape_slashes(html_text)):
        m = MAPHILIGHTED_IMG_RE.search(text)
        if m:
            return make_absolute(m.group(1))

        m = FULL_IMG_RE.search(text)
        if m:
            return make_absolute(m.group(0))

        m = JSON_IMAGE_KEY_RE.search(text)
        if m:
            url = m.group(1)
            if "issues" in url.lower() or url.lower().endswith((".jpg", ".jpeg", ".png")):
                return make_absolute(url)

        m = OG_IMAGE_RE.search(text)
        if m:
            url = m.group(1)
            if url.lower().endswith((".jpg", ".jpeg", ".png")):
                return make_absolute(url)

    return None


def get_page_image_url(session, station_id, page_id):
    url = f"{BASE}/epaper?station_id={station_id}&page_id={page_id}"
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

    page_ids = get_page_id_list(session, station_id)
    if not page_ids:
        log(f"==> {edition_name}: page list scrape se nahi mili, "
            f"fallback try kar rahe hain (page_id guess nahi ho sakta, "
            f"is liye ye edition FAIL ho sakta hai -- site ka page-list "
            f"HTML structure badal gaya ho sakta hai).")
        return None

    log(f"==> {edition_name}: {len(page_ids)} pages mile.")

    def worker(idx_pid):
        idx, pid = idx_pid
        img_url = get_page_image_url(session, station_id, pid)
        if img_url is None:
            log(f"    [{edition_name}] page {idx+1} (page_id={pid}): image URL nahi mili (skip)")
            return idx, None
        content = download_and_verify_image(session, img_url)
        if content is None:
            log(f"    [{edition_name}] page {idx+1} (page_id={pid}): download FAIL (skip)")
        else:
            log(f"    [{edition_name}] page {idx+1}/{len(page_ids)}: OK ({len(content)} bytes)")
        return idx, content

    downloaded = [None] * len(page_ids)
    with concurrent.futures.ThreadPoolExecutor(max_workers=THREADS_PER_EDITION) as ex:
        for idx, content in ex.map(worker, enumerate(page_ids)):
            downloaded[idx] = content

    pil_images = []
    if keep_images:
        tag = f"{edition_name}_{today_pkt_str()}"
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
        pretty_date = datetime.now(PKT).strftime("%d%B")  # e.g. 12July
    except ValueError:
        pretty_date = today_pkt_str()

    pdf_name = f"Khabrain {edition_name.replace('_', ' ')} {pretty_date}.pdf"
    pdf_path = os.path.join(outdir, pdf_name)

    first, rest = pil_images[0], pil_images[1:]
    first.save(pdf_path, save_all=True, append_images=rest)
    log(f"==> {edition_name}: PDF ban gayi -> {pdf_path}  ({len(pil_images)}/{len(page_ids)} pages)")
    if len(pil_images) < len(page_ids):
        log(f"    NOTE: {len(page_ids) - len(pil_images)} page(s) is edition mein download nahi ho sake.")
    return pdf_path


def main():
    parser = argparse.ArgumentParser(description="Daily Khabrain Epaper auto downloader -> PDF")
    all_choices = list(EDITIONS.keys()) + [SUNDAY_MAGAZINE_NAME]
    parser.add_argument(
        "--editions",
        nargs="+",
        choices=all_choices,
        default=None,
        help=(
            "Sirf in editions ko download karein (default: sab 8 city "
            "editions + agar aaj Sunday hai to Sunday Magazine bhi)."
        ),
    )
    parser.add_argument(
        "--outdir",
        default=os.path.join(os.getcwd(), "Khabrain_Epaper_PDFs"),
        help="PDF output folder",
    )
    parser.add_argument(
        "--keep-images",
        action="store_true",
        help="Har page ki alag JPG bhi rakhein (_raw folder mein).",
    )
    parser.add_argument(
        "--debug-dump",
        metavar="STATION_ID:PAGE_ID",
        default=None,
        help=(
            "Debug mode: sirf ek page ki raw HTML "
            "'khabrain_debug_page.html' mein save kar dega (koi PDF nahi "
            "banegi). Agar image URL phir bhi na mile to ye file kisi "
            "ko bhej kar regex fix karwaya ja sakta hai. "
            "Misaal: --debug-dump 7:261596"
        ),
    )
    args = parser.parse_args()

    if args.debug_dump:
        try:
            sid_str, pid_str = args.debug_dump.split(":")
            sid, pid = int(sid_str), int(pid_str)
        except ValueError:
            sys.exit("--debug-dump ka format STATION_ID:PAGE_ID hona chahiye, misaal: 7:261596")
        session = make_session()
        url = f"{BASE}/epaper?station_id={sid}&page_id={pid}"
        r = http_get(session, url)
        if r is None:
            sys.exit(f"Page fetch nahi ho saka: {url}")
        out_path = "khabrain_debug_page.html"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(r.text)
        found = extract_full_image_url(r.text)
        log(f"Raw HTML save ho gayi: {out_path} ({len(r.text)} chars)")
        log(f"Extractor ka result: {found or 'KUCH NAHI MILA'}")
        log("Agar 'KUCH NAHI MILA' aaya to khabrain_debug_page.html file "
            "kisi ko bhej kar dikhayein taake regex theek se fix ho sake.")
        return

    os.makedirs(args.outdir, exist_ok=True)
    log(f"Output folder: {args.outdir}")
    log(f"Aaj ki tareekh (PKT): {today_pkt_str()}")

    if args.editions:
        chosen = args.editions
    else:
        chosen = list(EDITIONS.keys())
        if is_today_sunday_pkt():
            log("Aaj Sunday hai -> Sunday Magazine bhi download hogi (alag PDF).")
            chosen = chosen + [SUNDAY_MAGAZINE_NAME]
        else:
            log("Aaj Sunday nahi hai -> Sunday Magazine skip ho rahi hai.")

    log(f"Editions ({len(chosen)}): {', '.join(chosen)}")

    results = {}
    for name in chosen:
        station_id = SUNDAY_MAGAZINE_STATION if name == SUNDAY_MAGAZINE_NAME else EDITIONS[name]
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
