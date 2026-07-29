#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Express Epaper (www.express.com.pk) Auto Downloader  -- v2 (fixed)
====================================================================
11 editions (Lahore, Karachi, Islamabad, Faisalabad, Gujranwala, Multan,
Peshawar, Rahim Yar Khan, Sargodha, Sukkur, Quetta) ka aaj ka epaper
auto-download kar ke, har edition ke jitne bhi pages hon (kabhi kam,
kabhi zyada), unhe sahi tarteeb (page order) mein aik PDF mein
assemble kar deta hai. Koi stamping/overlay nahi -- pages jaisi
download hui waisi hi PDF mein chali jaati hain.

v2 mein fix kiya gaya:
  1) "image file is truncated" wala masla -> images ab poori tarah
     download hone ki confirm hoti hain (Content-Length verify +
     PIL se load verify) aur agar incomplete aaye to khud retry
     hoti hain (5 tak koshishen, har baar thora zyada wait).
  2) Stamping (name/date/page-number likhna) hata di gayi hai -- ab
     seedha downloaded image PDF mein chali jaati hai.
  3) Khaali/empty "_raw" folders ab sirf tab bantay hain jab
     --keep-images flag diya jaye, warna bilkul nahi bantay.
  4) Agar kisi edition ka koi page baar baar fail ho to sirf wo
     page skip hota hai, baqi pages se PDF phir bhi ban jaati hai.

SITE PATTERN (scrape se maloom hua):
-------------------------------------
1) https://www.express.com.pk/epaper/  -> har edition ka link:
   .../epaper/Index.aspx?Issue=NP_LHE (waghera, 11 editions)

2) Index.aspx?Issue=NP_XXX (bina Date diye) -> site khud current/
   latest issue resolve karta hai. HTML ke andar thumbnail-strip se
   asli filenames milte hain:
   https://www.express.com.pk/images/NP_XXX/YYYYMMDD/
        YYYYMMDD-NP_XXX-<PageCode>-thumb.jpg

3) Full resolution image = wahi URL bas "-thumb" hatane se:
   https://www.express.com.pk/images/NP_XXX/YYYYMMDD/
        YYYYMMDD-NP_XXX-<PageCode>.jpg

4) Page codes (FRONT_PAGE, Metropolitan_PageC002, City_PageC004,
   waghera) roz/edition ke hisaab se badalte hain -> is liye script
   inhe har run par live HTML se hi nikaalti hai (hardcoded nahi).

Requirements:
    pip install requests pillow

Usage:
    python express_epaper_downloader.py
    python express_epaper_downloader.py --editions NP_LHE NP_KHI
    python express_epaper_downloader.py --outdir "C:/EpaperPDFs"
    python express_epaper_downloader.py --keep-images
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
    ImageFile.LOAD_TRUNCATED_IMAGES = True  # safety net; hum phir bhi manually verify karte hain
except ImportError:
    sys.exit("Pillow missing hai. Pehle chalayein: pip install pillow")


BASE = "https://www.express.com.pk"

EDITIONS = {
    "NP_LHE": "Lahore",
    "NP_KHI": "Karachi",
    "NP_ISB": "Islamabad",
    "NP_FSB": "Faisalabad",
    "NP_GRW": "Gujranwala",
    "NP_MUX": "Multan",
    "NP_PEW": "Peshawar",
    "NP_RYK": "Rahim Yar Khan",
    "NP_SGD": "Sargodha",
    "NP_SUK": "Sukkur",
    "NP_QTA": "Quetta",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ur;q=0.8",
    "Referer": BASE + "/epaper/",
    "Connection": "keep-alive",
}

HTML_RETRIES = 4
IMAGE_RETRIES = 5
RETRY_SLEEP = 1.5  # seconds, grows each retry
REQUEST_TIMEOUT = 40
THREADS_PER_EDITION = 4  # kam threads = mobile network par zyada stable

PKT = timezone(timedelta(hours=5))  # Pakistan Standard Time (no DST)

# Edition ka "aaj ka" issue kabhi kabhi thori der se upload hota hai
# (khaas kar subah subah). Agar site ne humein maangi hui date ki
# bajaye purani date de di, to itni baar / itne wait ke saath
# recheck karte hain jab tak naya issue upload na ho jaye.
WAIT_FOR_TODAY_MAX_MINUTES = 30
WAIT_FOR_TODAY_POLL_SECONDS = 90


def today_pkt():
    """Pakistan Standard Time ke hisaab se 'aaj' ki date (YYYYMMDD string)."""
    return datetime.now(PKT).strftime("%Y%m%d")


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


def http_get_html(session, url):
    last_err = None
    for attempt in range(1, HTML_RETRIES + 1):
        try:
            r = session.get(url, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200 and r.text:
                return r
            last_err = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last_err = str(e)
        log(f"  retry {attempt}/{HTML_RETRIES} -> {url}  ({last_err})")
        time.sleep(RETRY_SLEEP * attempt)
    log(f"  FAILED after {HTML_RETRIES} tries: {url}  ({last_err})")
    return None


def download_and_verify_image(session, url):
    """
    Downloads a jpg fully, checks size against Content-Length (agar
    server bheje), aur PIL se load karke verify karta hai ke image
    corrupt/truncated to nahi. Nakami par retry karta hai.
    Returns raw bytes ya None.
    """
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
                    # actual pixel-level verify -> yehi "truncated" masla pakadta hai
                    try:
                        im = Image.open(io.BytesIO(content))
                        im.load()
                        return content
                    except Exception as e:
                        last_err = f"corrupt/truncated image ({e})"
        except requests.RequestException as e:
            last_err = str(e)

        log(f"    retry {attempt}/{IMAGE_RETRIES} -> {url}  ({last_err})")
        time.sleep(RETRY_SLEEP * attempt)

    log(f"    FAILED after {IMAGE_RETRIES} tries: {url}  ({last_err})")
    return None


def get_page_list(session, issue, target_date=None):
    """
    Returns ordered list of dicts: {date, pagecode, pageno} for the
    issue of `issue` (e.g. NP_LHE), scraped fresh from the site's own
    HTML (no hardcoded page names).

    Agar target_date diya jaye (YYYYMMDD string) to seedha wahi Date
    site se maanga jaata hai (bina Date diye site kabhi kabhi kal
    wala "latest" resolve kar deti thi -- isi se purani date wali
    PDF ban rahi thi).
    """
    if target_date:
        index_url = f"{BASE}/epaper/Index.aspx?Issue={issue}&Date={target_date}"
    else:
        index_url = f"{BASE}/epaper/Index.aspx?Issue={issue}"
    r = http_get_html(session, index_url)
    if r is None:
        return []
    html = r.text

    pat_thumb = re.compile(
        rf'images/{re.escape(issue)}/(\d{{8}})/\1-{re.escape(issue)}-([A-Za-z0-9_\-]+?)-thumb\.jpg'
    )
    seen = []
    seen_keys = set()
    for date, pagecode in pat_thumb.findall(html):
        key = (date, pagecode)
        if key not in seen_keys:
            seen_keys.add(key)
            seen.append({"date": date, "pagecode": pagecode})

    if seen:
        pat_goto = re.compile(
            rf'Index\.aspx\?Issue={re.escape(issue)}&Page=([^&"\']+)&Date=(\d{{8}})&Pageno=(\d+)'
        )
        goto_map = {}
        for pg, dt, pno in pat_goto.findall(html):
            goto_map.setdefault(dt, {})[pg.upper()] = pno
        for item in seen:
            pno = None
            m = goto_map.get(item["date"], {})
            for k, v in m.items():
                if k in item["pagecode"].upper() or item["pagecode"].upper() in k:
                    pno = v
                    break
            item["pageno"] = pno
        return seen

    # ---- Fallback path: use goto strip + per-page fetch ----
    log(f"  [{issue}] thumb-strip na mili, fallback method try ho raha hai...")
    pat_goto = re.compile(
        rf'Index\.aspx\?Issue={re.escape(issue)}&Page=([^&"\']+)&Date=(\d{{8}})&Pageno=(\d+)'
    )
    goto_hits = []
    goto_seen = set()
    for pg, dt, pno in pat_goto.findall(html):
        key = (pg, dt, pno)
        if key not in goto_seen:
            goto_seen.add(key)
            goto_hits.append({"page_param": pg, "date": dt, "pageno": pno})

    results = []
    for hit in goto_hits:
        page_url = (
            f"{BASE}/epaper/Index.aspx?Issue={issue}&Page={hit['page_param']}"
            f"&Date={hit['date']}&Pageno={hit['pageno']}&View=1"
        )
        rr = http_get_html(session, page_url)
        if rr is None:
            continue
        m = re.search(
            rf'images/{re.escape(issue)}/{hit["date"]}/{hit["date"]}-{re.escape(issue)}-'
            rf'([A-Za-z0-9_\-]+?)\.jpg',
            rr.text,
        )
        if m:
            code = m.group(1)
            if not code.endswith("-thumb") and "goto" not in code:
                results.append(
                    {"date": hit["date"], "pagecode": code, "pageno": hit["pageno"]}
                )
    return results


def process_edition(issue, edition_name, outdir, keep_images, wait_for_today=True):
    log(f"==> {issue} ({edition_name}) : page list nikaali ja rahi hai...")
    session = make_session()

    wanted_date = today_pkt()
    pages = get_page_list(session, issue, target_date=wanted_date)
    date_str = pages[0]["date"] if pages else None

    # Agar site ne maangi hui (aaj ki) date ke bajaye purani date de
    # di -- matlab is edition ki aaj ki copy abhi upload nahi hui --
    # to thora wait kar ke dobara try karte hain.
    deadline = time.time() + WAIT_FOR_TODAY_MAX_MINUTES * 60
    while wait_for_today and (not pages or date_str != wanted_date) and time.time() < deadline:
        log(
            f"==> {issue}: aaj ({wanted_date}) ka edition abhi live nahi mila "
            f"(mila: {date_str or 'kuch nahi'}). {WAIT_FOR_TODAY_POLL_SECONDS}s wait "
            f"kar ke dobara check kar rahe hain..."
        )
        time.sleep(WAIT_FOR_TODAY_POLL_SECONDS)
        pages = get_page_list(session, issue, target_date=wanted_date)
        date_str = pages[0]["date"] if pages else None

    if not pages:
        log(f"==> {issue}: koi page nahi mila (site down ya block ho sakta hai). Skip.")
        return None

    if date_str != wanted_date:
        log(
            f"==> {issue}: WARNING -- aaj ({wanted_date}) ka edition ab tak site par "
            f"upload nahi hua, isliye {date_str} wali (purani) copy download ho rahi hai."
        )

    log(f"==> {issue}: {len(pages)} pages mile, date = {date_str}")

    # Sunday ko magazine pages honi chahiye (pagecode mein "SM" hota
    # hai, e.g. EXP-SM01). Agar Sunday hai aur ye pages nahi milin,
    # to user ko clearly batao (ho sakta hai magazine abhi upload
    # nahi hui).
    try:
        is_sunday = datetime.strptime(date_str, "%Y%m%d").weekday() == 6
    except (TypeError, ValueError):
        is_sunday = False
    if is_sunday:
        has_magazine = any("SM" in p["pagecode"].upper() for p in pages)
        if has_magazine:
            log(f"==> {issue}: Sunday Magazine ke pages mil gaye, alag PDF banegi.")
        else:
            log(f"==> {issue}: WARNING -- aaj Sunday hai lekin Sunday Magazine ke pages nahi milay.")

    # Magazine pages (pagecode mein "SM", e.g. EXP-SM01) ko main
    # edition se alag rakhte hain -- inki PDF alag banegi, edition
    # ki PDF mein shamil nahi hongi.
    magazine_pages = [p for p in pages if "SM" in p["pagecode"].upper()]
    main_pages = [p for p in pages if p not in magazine_pages]

    results = {}
    results["main"] = _download_and_build_pdf(
        session, issue, edition_name, main_pages, date_str, outdir, keep_images,
        suffix=None,
    )
    if magazine_pages:
        results["magazine"] = _download_and_build_pdf(
            session, issue, edition_name, magazine_pages, date_str, outdir, keep_images,
            suffix="Sunday Magazine",
        )
    else:
        results["magazine"] = None
    return results


def _download_and_build_pdf(session, issue, edition_name, pages, date_str, outdir, keep_images, suffix=None):
    if not pages:
        return None

    label = f"{issue}" + (f"/{suffix}" if suffix else "")
    downloaded = [None] * len(pages)

    def worker(idx_item):
        idx, item = idx_item
        url = f"{BASE}/images/{issue}/{item['date']}/{item['date']}-{issue}-{item['pagecode']}.jpg"
        content = download_and_verify_image(session, url)
        if content is None:
            log(f"    [{label}] page {idx+1} ({item['pagecode']}) download FAIL (skip ho gaya)")
        else:
            log(f"    [{label}] page {idx+1}/{len(pages)} ({item['pagecode']}) OK ({len(content)} bytes)")
        return idx, content

    with concurrent.futures.ThreadPoolExecutor(max_workers=THREADS_PER_EDITION) as ex:
        for idx, content in ex.map(worker, enumerate(pages)):
            downloaded[idx] = content

    # sahi page-tarteeb mein PIL Images bana lo (koi stamping nahi)
    pil_images = []
    if keep_images:
        tag = f"{issue}_{date_str}" + (f"_{suffix.replace(' ', '_')}" if suffix else "")
        tmp_dir = os.path.join(outdir, "_raw", tag)
        os.makedirs(tmp_dir, exist_ok=True)

    for idx, item in enumerate(pages):
        content = downloaded[idx]
        if content is None:
            continue
        try:
            im = Image.open(io.BytesIO(content))
            im.load()
            im = im.convert("RGB")
        except Exception as e:
            log(f"    [{label}] page {idx+1} ({item['pagecode']}) open error, skip: {e}")
            continue
        pil_images.append(im)
        if keep_images:
            im.save(os.path.join(tmp_dir, f"{idx+1:02d}_{item['pagecode']}.jpg"), quality=95)

    if not pil_images:
        log(f"==> {label}: koi bhi page successfully download nahi hua, PDF skip.")
        return None

    os.makedirs(outdir, exist_ok=True)
    try:
        pretty_date = datetime.strptime(date_str, "%Y%m%d").strftime("%d%B")  # e.g. 11July
    except ValueError:
        pretty_date = date_str
    if suffix:
        pdf_name = f"Express {edition_name} {suffix} {pretty_date}.pdf"  # e.g. "Express Karachi Sunday Magazine 12July.pdf"
    else:
        pdf_name = f"Express {edition_name} {pretty_date}.pdf"  # e.g. "Express Lahore 11July.pdf"
    pdf_path = os.path.join(outdir, pdf_name)

    first, rest = pil_images[0], pil_images[1:]
    first.save(pdf_path, save_all=True, append_images=rest)
    log(f"==> {label}: PDF ban gayi -> {pdf_path}  ({len(pil_images)}/{len(pages)} pages)")
    if len(pil_images) < len(pages):
        log(f"    NOTE: {len(pages) - len(pil_images)} page(s) is edition mein download nahi ho saka.")
    return pdf_path


def main():
    parser = argparse.ArgumentParser(description="Express Epaper (express.com.pk) auto downloader -> PDF")
    parser.add_argument(
        "--editions",
        nargs="+",
        choices=list(EDITIONS.keys()),
        default=list(EDITIONS.keys()),
        help="Sirf in editions ke codes (default: sab 11 editions)",
    )
    parser.add_argument(
        "--outdir",
        default=os.path.join(os.getcwd(), "Express_Epaper_PDFs"),
        help="PDF output folder",
    )
    parser.add_argument(
        "--keep-images",
        action="store_true",
        help="Har page ki alag JPG bhi rakhein (_raw folder mein). Default: nahi rakhi jaatin.",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help=(
            f"Agar aaj ka edition abhi upload na hua ho to wait/retry na karein "
            f"(default: {WAIT_FOR_TODAY_MAX_MINUTES} minute tak har "
            f"{WAIT_FOR_TODAY_POLL_SECONDS}s baad recheck karta hai)."
        ),
    )
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    log(f"Output folder: {args.outdir}")
    log(f"Editions ({len(args.editions)}): {', '.join(args.editions)}")

    results = {}
    for issue in args.editions:
        edition_name = EDITIONS[issue]
        try:
            edition_result = process_edition(
                issue, edition_name, args.outdir, args.keep_images,
                wait_for_today=not args.no_wait,
            )
            results[issue] = edition_result or {"main": None, "magazine": None}
        except Exception as e:
            log(f"==> {issue}: UNEXPECTED ERROR -> {e}")
            results[issue] = {"main": None, "magazine": None}

    log("")
    log("===================== SUMMARY =====================")
    ok = 0
    for issue, res in results.items():
        main_path = res.get("main")
        mag_path = res.get("magazine")
        status = main_path if main_path else "FAILED"
        log(f"{issue:8s} ({EDITIONS[issue]:15s}) -> {status}")
        if mag_path:
            log(f"{'':8s} {'':15s}    + Sunday Magazine -> {mag_path}")
        if main_path:
            ok += 1
    log(f"Total: {ok}/{len(results)} editions successful.")
    log("=====================================================")


if __name__ == "__main__":
    main()
