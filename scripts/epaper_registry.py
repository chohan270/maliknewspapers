# -*- coding: utf-8 -*-
"""
Central registry of every newspaper downloader script.

Har entry ka matlab:
  script       -> scripts/ folder mein filename
  mode:
     "argparse" -> script khud "--outdir <path>" support karta hai aur
                   ek hi run mein SAB editions download kar deta hai.
     "cwd"      -> script ke paas koi CLI/outdir option nahi hai; ye
                   apne current working directory ke andar khud apna
                   relative folder bana kar (e.g. "Jang_PDFs/") PDFs
                   waha save karta hai. Isliye hum isko ek dedicated
                   temp working-directory mein run karte hain aur run
                   ke baad us folder ke andar (recursively) *.pdf
                   dhoond lete hain -- naam/subfolder kuch bhi ho, kaam
                   ho jata hai.
  extra_args   -> script ko diye jane wale additional CLI args
  batch        -> "express" (3:00 AM slot) ya "baqi" (4:30/5:00 AM slot)
  sunday_only  -> True matlab ye sirf Sunday ko chalega (Sunday Magazine)
  display      -> Insani-parhne-laiq naam (status/report messages ke liye)
"""

NEWSPAPERS = {
    # ---------------- EXPRESS (apni alag batch/schedule) ----------------
    "express": {
        "display": "Express",
        "script": "express.py",
        "mode": "argparse",
        "extra_args": ["--no-wait"],
        "batch": "express",
    },

    # ---------------- BAQI (4:30 download / 5:00 send batch) ------------
    "jang": {
        "display": "Jang",
        "script": "jang.py",
        "mode": "cwd",
        "batch": "baqi",
    },
    "jangsundaymagazine": {
        "display": "Jang Sunday Magazine",
        "script": "jangsundaymagazine.py",
        "mode": "cwd",
        "batch": "baqi",
        "sunday_only": True,
    },
    "thenews": {
        "display": "The News",
        "script": "thenews.py",
        "mode": "cwd",
        "batch": "baqi",
    },
    "dawn": {
        "display": "Dawn",
        "script": "dawn.py",
        "mode": "cwd",
        "batch": "baqi",
    },
    "asas": {
        "display": "Asas",
        "script": "asas.py",
        "mode": "cwd",
        "batch": "baqi",
    },
    "nawaiwaqt": {
        "display": "Nawaiwaqt",
        "script": "nawaiwaqt.py",
        "mode": "cwd",
        "batch": "baqi",
        # Nawaiwaqt script khud hi Sunday Magazine ko internally handle
        # karta hai (agar Sunday ho), koi extra flag nahi chahiye.
    },
    "dailypakistan": {
        "display": "Daily Pakistan",
        "script": "dailypakistan.py",
        "mode": "cwd",
        "batch": "baqi",
    },
    "khabrain": {
        "display": "Khabrain",
        "script": "khabrain.py",
        "mode": "argparse",
        "batch": "baqi",
        # Khabrain script khud Sunday Magazine ko apne "--editions" default
        # list mein add kar leta hai jab aaj Sunday ho.
    },
    "naibaat": {
        "display": "Nai Baat",
        "script": "naibaat.py",
        "mode": "cwd",
        "batch": "baqi",
    },
    "naibaatmagazine": {
        "display": "Nai Baat Magazine",
        "script": "naibaatmagazine.py",
        "mode": "cwd",
        "batch": "baqi",
        "sunday_only": True,
    },
    "countrynews": {
        "display": "Country News",
        "script": "countrynews.py",
        "mode": "argparse",
        "batch": "baqi",
    },
    "parliamenttimes": {
        "display": "Parliament Times",
        "script": "parliamenttimes.py",
        "mode": "argparse",
        "batch": "baqi",
    },
    "sahafat": {
        "display": "Sahafat",
        "script": "sahafat.py",
        "mode": "argparse",
        "batch": "baqi",
    },
    "jasarat": {
        "display": "Jasarat",
        "script": "jasarat.py",
        "mode": "argparse",
        "batch": "baqi",
    },
    "jehanpakistan": {
        "display": "Jehan Pakistan",
        "script": "jehanpakistan.py",
        "mode": "cwd",
        "batch": "baqi",
    },
    "islamk": {
        "display": "Islam Karachi",
        "script": "islamk.py",
        "mode": "cwd",
        "batch": "baqi",
    },
    "mashriq": {
        "display": "Mashriq",
        "script": "mashriq.py",
        "mode": "cwd",
        "batch": "baqi",
    },
    "baithak": {
        "display": "Baithak",
        "script": "baithak.py",
        "mode": "cwd",
        "batch": "baqi",
    },
    "ghaznavi": {
        "display": "Ghaznavi",
        "script": "ghaznavi.py",
        "mode": "cwd",
        "batch": "baqi",
    },
    "intekhab": {
        "display": "Daily Intekhab",
        "script": "intekhab.py",
        "mode": "cwd",
        "batch": "baqi",
    },
    "kawish": {
        "display": "Kawish",
        "script": "kawish.py",
        "mode": "argparse",
        "batch": "baqi",
    },
    "mahasib": {
        "display": "Mahasib",
        "script": "mahasib.py",
        "mode": "cwd",
        "batch": "baqi",
    },
    "pakobserver": {
        "display": "Pakistan Observer",
        "script": "pakobserver.py",
        "mode": "argparse",
        "batch": "baqi",
    },
    "thenation": {
        "display": "The Nation",
        "script": "thenation.py",
        "mode": "cwd",
        "batch": "baqi",
    },
    "ummat": {
        "display": "Ummat",
        "script": "ummat.py",
        "mode": "cwd",
        "batch": "baqi",
    },
}


def editions_for_batch(batch_name, is_sunday):
    """Batch (express/baqi) ke liye aaj chalne wali editions ki list,
    Sunday-only wali un dinon exclude kar deta hai jab Sunday na ho."""
    out = []
    for key, cfg in NEWSPAPERS.items():
        if cfg["batch"] != batch_name:
            continue
        if cfg.get("sunday_only") and not is_sunday:
            continue
        out.append(key)
    return out


def all_batches():
    return sorted({cfg["batch"] for cfg in NEWSPAPERS.values()})
