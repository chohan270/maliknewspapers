# Malik MD — Epaper Auto-Forward WhatsApp Bot (Heroku)

Ye repo aapka mojooda Baileys bot hai + **poora automated Epaper system**
add kiya gaya hai (26 newspapers: Express, Jang, The News, Dawn, Nawaiwaqt,
Jasarat, Khabrain waghera).

## 🧠 Kaise kaam karta hai

```
Node.js bot (index.js)
    │
    │  node-cron schedule fire hota hai (Asia/Karachi time)
    ▼
maliklib/epaperEngine.js
    │
    │  spawn: python3 scripts/epaper_scheduler.py --batch express|baqi
    ▼
scripts/epaper_scheduler.py
    │  1. Har newspaper script chalata hai (/tmp/epaper_work/<name>/ mein)
    │  2. Har script ki PDF(s) dhoondta hai
    │  3. scripts/wm.py se watermark karta hai
    │  4. Watermarked PDFs /tmp/epaper_outbox/ mein rakhta hai
    │  5. Result JSON print karta hai (EPAPER_RESULT_JSON:{...})
    ▼
epaperEngine.js wapis control leta hai
    │  1. WhatsApp groups ko document bhejta hai (fresh sendMessage — NO
    │     "Forwarded" tag)
    │  2. MongoDB mein "sent" mark karta hai (duplicate-skip)
    │  3. /tmp se file delete karta hai (WhatsApp group se NAHI)
    │  4. Jo newspaper fail ho, use "pendingRetries" list mein daal deta hai
    ▼
Har 15 minute (3AM–10AM) retryTick() sirf failed newspapers dobara try
karta hai, jab tak maxRetries (default 4) khatam na ho.
```

### Schedule (Asia/Karachi time)

| Time | Kaam |
|---|---|
| 3:00 AM (Mon–Sat) | Express: 11 editions **ek sath (parallel)** download → jo bhi pehle ban jaye turant send |
| 5:30 AM (Sunday only) | Express (Sunday ko baad mein) |
| 4:30 AM (daily) | Baqi 25 newspapers: **ek sath (parallel, up to 6 at a time)** download + watermark |
| 5:00 AM (daily) | Baqi 25 newspapers: jo ban chuki unko send + delete |
| Har 15 min, 3AM–11:45PM | Sirf FAILED newspapers dobara try — **koi attempt-limit nahi**, jab tak wo ban na jaye tab tak poore din chalti rahegi |

Newspapers ab **ek ek karke nahi, balke ek sath (parallel, max 6 simultaneously)**
chalte hain — is se do fayde hain:
1. **Speed** — 26 scripts sequentially ~30-60 min lagte, ab parallel mein bohat
   kam waqt (fast newspapers jaldi ban kar chali jati hain).
2. **Koi ek atki hui newspaper baaki ko block nahi karti** — agar "X" newspaper
   ka server slow hai ya down hai, "Y", "Z" waghera sath mein chalte rehte hain
   aur apni waqt par ban kar WhatsApp par chali jati hain. Sirf "X" retry-queue
   mein chali jati hai aur har 15 min try hoti rehti hai **jab tak ban na
   jaye** — chahe pura din lag jaye.


---

## 📲 WhatsApp Commands

Sab commands **owner-only** hain (jis number se bot connect hai, wahi use
kar sakta hai — ya `.env`/DB mein defined sudo).

```
.af epaper set 12345@g.us, 67890@g.us    → target groups set karo (multiple, comma-separated)
.af epaper on                            → auto-system ON
.af epaper off                           → auto-system OFF
.af epaper run                           → abhi turant Express + Baqi + retries chalao (manual)
.af epaper                               → status dekho (ON/OFF, targets, last run, pending retries)
```

Group ka JID nikalne ke liye group mein `.af` bhej dein — ya jo bhi purana
JID-finder command (`gjids`/`jid`) already bot mein hai, wahi use karein.

---

## 🚀 Heroku Deployment — Step by Step

### 1. Repo push karein
```bash
git init
git add .
git commit -m "Epaper auto-system added"
heroku git:remote -a qasimraza
git push heroku main
```

### 2. Buildpacks (agar app.json se auto na lagein to manually)
```bash
heroku buildpacks:clear -a qasimraza
heroku buildpacks:add heroku-community/apt -a qasimraza
heroku buildpacks:add heroku/python -a qasimraza
heroku buildpacks:add heroku/nodejs -a qasimraza
```
> Order zaroori hai: pehle **apt** (system packages: ffmpeg, git),
> phir **python** (requirements.txt: pypdf, pillow, requests, curl_cffi),
> phir **nodejs** (package.json: node-cron, fs-extra waghera).
> Sab kuch build ke waqt khud install ho jayega — kuch bhi manually
> download karne ki zaroorat nahi.

### 3. Config Vars (SIRF YE DO — koi aur nahi chahiye)
```bash
heroku config:set SESSION_ID=your-session-id -a qasimraza
heroku config:set MONGODB_URI="mongodb+srv://user:pass@cluster.mongodb.net/db" -a qasimraza
```

### 4. Dyno chalayein
```bash
heroku ps:scale web=1 -a qasimraza
heroku logs --tail -a qasimraza
```

### 5. Pehli dafa connect karein
Deploy hone ke baad `https://qasimraza-<hash>.herokuapp.com/` khol kar QR
scan karein (ya pairing code route use karein — jo pehle se app mein hai).
Connect hote hi terminal mein ye line dikhegi:
```
🗞️  Epaper cron registered (Asia/Karachi): Express 3:00 AM (Sun 5:30 AM) | Baqi 4:30/5:00 AM | retries every 15 min till 10 AM
```

### 6. WhatsApp se target groups set karein
```
.af epaper set 923001234567-1234567890@g.us
.af epaper on
.af epaper run     ← (test ke liye — abhi turant chala kar dekh lein)
```

---

## ⚠️ Zaroori note — Dyno neend (sleep)

Eco/Basic dynos 30 min ki inactivity ke baad so jate hain — agar dyno so
gaya to 3AM/4:30AM ka cron miss ho sakta hai. Isse bachne ke liye:
- Heroku **Eco/Basic dyno** use karein (paid, sleep nahi hota), **ya**
- Koi external uptime-pinger (UptimeRobot/cron-job.org) har 10-15 min
  par aapke app ke root URL (`/`) ko ping karta rahay, taake dyno
  hamesha jaaga rahe aur node-cron waqt par fire ho.

Ye system ka koi hissa nahi hai jo aapse manually control ho — bas dyno
ka uthe rehna zaroori hai taake cron chal sake.

---

## 📁 Naye/Modified files ka summary

| File | Kya kiya |
|---|---|
| `scripts/*.py` (26 files) | Aapki original scripts, **bina kisi tabdeeli ke** copy |
| `scripts/wm.py` | Same watermark logic, sirf paths portable (Heroku-safe) |
| `scripts/assets/{express.png, pbk.png, pbk.pdf}` | Watermark assets |
| `scripts/epaper_registry.py` | **NEW** — har newspaper ka mode/batch/Sunday config |
| `scripts/epaper_scheduler.py` | **NEW** — download+watermark orchestrator |
| `requirements.txt`, `.python-version` | **NEW** — Python deps + version |
| `Aptfile` | python3-pip/venv add kiya |
| `app.json` | `heroku/python` buildpack add kiya |
| `package.json` | `node-cron`, `fs-extra` add kiye |
| `maliklib/database.js` | `EpaperConfig` + `EpaperSentFile` schemas/functions add |
| `maliklib/epaperEngine.js` | **NEW** — cron, python-spawn, WhatsApp send, retry logic |
| `malikplugins/autoforward.js` | `.af epaper set/on/off/run` commands add |
| `index.js` | Connection open hone par `epaperEngine.init()` call |
| `.env.example` | Sirf `SESSION_ID` + `MONGODB_URI` |

Baaki files (`malikplugins/forward.js`, `gjids.js`, `jid.js`, `menu.js`,
`ping.js`, `uptime.js`, `maliklib/session.js`, `mongoAuth.js`,
`cleaner.js`, `public/index.html`, `Dockerfile`, `Procfile`,
`ecosystem.config.json`) **bilkul waisi hi hain jaisi aapki original zip
mein thi** — kuch chhera nahi gaya.
