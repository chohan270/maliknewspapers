#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
epaper_scheduler.py
====================
Node bot (maliklib/epaperEngine.js) is script ko subprocess ke tor par
chalata hai. Kaam:

  1. Diye gaye newspaper "keys" (ya --batch express/baqi) ke liye har
     script ko chalao (Heroku /tmp ke andar, per-script dedicated
     working directory mein -- taake koi do scripts ek dusre ki
     files overwrite na karein).
  2. Har script ki output PDFs dhoondo (argparse-wale scripts ke liye
     --outdir se, cwd-wale scripts ke liye unki working-dir ke andar
     recursively *.pdf dhoond kar).
  3. Har raw PDF ko wm.py (process_pdf) se watermark karke ek common
     "outbox" folder mein final naam ke sath rakh do.
  4. Aakhir mein STDOUT par EXACT ek line:
         EPAPER_RESULT_JSON:{...}
     print karo jisay Node parse karta hai. (Node stdout ke baaki
     lines sirf logs ki tarah dikha deta hai.)

Ye script kabhi bhi non-zero exit code nahi deta (jab tak startup hi
crash na ho jaye) -- har newspaper ki success/failure JSON ke andar
"status" field mein hoti hai, taake Node hamesha result parse kar sake.

Usage:
    python3 epaper_scheduler.py --batch express --workdir /tmp/epaper_work --outdir /tmp/epaper_outbox
    python3 epaper_scheduler.py --editions jang dawn ummat --workdir /tmp/epaper_work --outdir /tmp/epaper_outbox
"""

import argparse
import concurrent.futures
import glob
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
    PKT = ZoneInfo("Asia/Karachi")
except Exception:
    PKT = None

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from epaper_registry import NEWSPAPERS, editions_for_batch  # noqa: E402
import wm  # noqa: E402  -- imported once; wm.process_pdf() is called per-PDF below

# Per-newspaper hard timeout (safety net so one stuck script can't hang
# the whole 3AM/4:30AM run forever).
PER_SCRIPT_TIMEOUT_SECONDS = int(os.environ.get("EPAPER_SCRIPT_TIMEOUT", "900"))  # 15 min

# Kitni newspapers ek sath (parallel) chal sakti hain -- taake ek slow/atki
# hui script baaki fast newspapers ko block na kare. subprocess.run() apna
# wait GIL release karta hai, isliye thread-pool yahan bilkul theek kaam
# karta hai (asal kaam alag python processes mein ho raha hota hai).
MAX_CONCURRENCY = int(os.environ.get("EPAPER_MAX_CONCURRENCY", "6"))


def now_pkt():
    if PKT:
        return datetime.now(PKT)
    return datetime.now()


def is_sunday_today():
    return now_pkt().weekday() == 6  # Monday=0 ... Sunday=6


def log(msg):
    print(f"[{now_pkt().strftime('%H:%M:%S')}] {msg}", flush=True)


def run_one(key, workdir_root, outbox_dir):
    cfg = NEWSPAPERS.get(key)
    if not cfg:
        return {"status": "failed", "display": key, "files": [], "error": "unknown newspaper key"}

    display = cfg["display"]
    script_path = os.path.join(SCRIPT_DIR, cfg["script"])
    if not os.path.exists(script_path):
        return {"status": "failed", "display": display, "files": [], "error": f"script not found: {cfg['script']}"}

    workdir = os.path.join(workdir_root, key)
    shutil.rmtree(workdir, ignore_errors=True)
    os.makedirs(workdir, exist_ok=True)

    raw_out_dir = os.path.join(workdir, "raw_out")
    os.makedirs(raw_out_dir, exist_ok=True)

    cmd = [sys.executable, script_path]
    if cfg["mode"] == "argparse":
        cmd += ["--outdir", raw_out_dir]
    cmd += cfg.get("extra_args", [])

    log(f"▶️  {display} ({key}) start -> {' '.join(cmd)}")
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=workdir,
            timeout=PER_SCRIPT_TIMEOUT_SECONDS,
            capture_output=True,
            text=True,
        )
        stdout_tail = "\n".join(proc.stdout.strip().splitlines()[-15:]) if proc.stdout else ""
        stderr_tail = "\n".join(proc.stderr.strip().splitlines()[-15:]) if proc.stderr else ""
        if proc.returncode != 0:
            log(f"⚠️  {display}: exit code {proc.returncode}\n{stderr_tail}")
    except subprocess.TimeoutExpired:
        log(f"⏱️  {display}: timed out after {PER_SCRIPT_TIMEOUT_SECONDS}s")
        stdout_tail, stderr_tail = "", "timeout"
    except Exception as e:
        log(f"❌ {display}: crashed launching script: {e}")
        return {"status": "failed", "display": display, "files": [], "error": str(e)}

    # Collect raw PDFs -- from --outdir (argparse mode) or anywhere under
    # the working dir (cwd mode, whatever relative folder the script used).
    search_root = raw_out_dir if cfg["mode"] == "argparse" else workdir
    raw_pdfs = sorted(glob.glob(os.path.join(search_root, "**", "*.pdf"), recursive=True))

    elapsed = round(time.time() - t0, 1)

    if not raw_pdfs:
        log(f"❌ {display}: no PDF produced ({elapsed}s)")
        return {
            "status": "failed",
            "display": display,
            "files": [],
            "error": (stderr_tail or stdout_tail or "no pdf produced")[:500],
        }

    # Watermark each raw PDF -> outbox, keeping the script's own filename
    # (this preserves each script's own naming convention, e.g.
    # "Jasarat Karachi 19Jul.pdf").
    final_files = []
    for raw_pdf in raw_pdfs:
        out_name = os.path.basename(raw_pdf)
        out_path = os.path.join(outbox_dir, out_name)
        try:
            wm.process_pdf(raw_pdf, out_path)
            final_files.append(out_path)
        except Exception as e:
            log(f"⚠️  {display}: watermark failed for {out_name}: {e}")

    # Raw (un-watermarked) working files no longer needed -- keep temp dir
    # small; final watermarked copies already live in outbox_dir.
    shutil.rmtree(workdir, ignore_errors=True)

    if not final_files:
        return {"status": "failed", "display": display, "files": [], "error": "watermark step failed for all pages"}

    log(f"✅ {display}: {len(final_files)} file(s) ready ({elapsed}s)")
    return {"status": "ok", "display": display, "files": final_files, "error": None}


def main():
    parser = argparse.ArgumentParser(description="Epaper download + watermark orchestrator")
    parser.add_argument("--batch", choices=["express", "baqi"], default=None,
                         help="Run the default edition-set for this batch (respects Sunday-only rules)")
    parser.add_argument("--editions", nargs="+", default=None,
                         help="Explicit list of newspaper keys to run (used for retries / manual run)")
    parser.add_argument("--workdir", default="/tmp/epaper_work", help="Scratch working directory root")
    parser.add_argument("--outdir", default="/tmp/epaper_outbox", help="Final watermarked PDF output folder")
    args = parser.parse_args()

    os.makedirs(args.workdir, exist_ok=True)
    os.makedirs(args.outdir, exist_ok=True)

    if args.editions:
        keys = args.editions
    elif args.batch:
        keys = editions_for_batch(args.batch, is_sunday_today())
    else:
        print("EPAPER_RESULT_JSON:" + json.dumps({}))
        return

    log(f"=== Epaper run: {len(keys)} newspaper(s), up to {MAX_CONCURRENCY} at a time -> {keys}")

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as executor:
        future_to_key = {
            executor.submit(run_one, key, args.workdir, args.outdir): key
            for key in keys
        }
        for future in concurrent.futures.as_completed(future_to_key):
            key = future_to_key[future]
            try:
                r = future.result()
            except Exception as e:
                log(f"❌ {key}: unexpected crash: {e}\n{traceback.format_exc()}")
                r = {"status": "failed", "display": key, "files": [], "error": str(e)}
            results[key] = r
            # Stream this ONE newspaper's result immediately -- Node acts on
            # it right away (send to WhatsApp) instead of waiting for every
            # other (possibly slower/failing) newspaper to also finish.
            print("EPAPER_ITEM_JSON:" + json.dumps({"key": key, **r}), flush=True)

    ok_count = sum(1 for r in results.values() if r["status"] == "ok")
    log(f"=== Done: {ok_count}/{len(keys)} succeeded")

    # Machine-readable aggregate result -- ALWAYS the last line of stdout
    # (kept for backward-compatible summary use).
    print("EPAPER_RESULT_JSON:" + json.dumps(results), flush=True)


if __name__ == "__main__":
    main()
