/**
 * ⚡ MALIK MD AUTOFORWARD BOT — EPAPER AUTOMATION ENGINE ⚡
 *
 * Pipeline (per requirements):
 *   Express : 3:00 AM (Sunday 5:30 AM) -> download -> watermark -> send -> delete /tmp
 *   Baqi    : 4:30 AM download (held) -> 5:00 AM send -> delete /tmp
 *   Failed newspapers only: retried every 15 minutes, no attempt limit
 *
 * MEMORY DESIGN (512MB Heroku dyno): every single newspaper runs in its own
 * short-lived `python3 epaper_scheduler.py --editions <key>` process. That
 * process downloads, watermarks, prints its result, and exits -- so its
 * memory is 100% handed back to the OS -- BEFORE the next newspaper's
 * process is even started, and usually before the next one is even
 * requested (each finished PDF is sent + deleted first). Nothing here ever
 * runs multiple newspapers inside one long-lived python process.
 */
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs-extra');
const cron = require('node-cron');

const {
    malik_getEpaperConfig,
    malik_updateEpaperConfig,
    malik_isEpaperFileSent,
    malik_markEpaperFileSent
} = require('./database');

const SCRIPTS_DIR = path.join(__dirname, '..', 'scripts');
const SCHEDULER_PY = path.join(SCRIPTS_DIR, 'epaper_scheduler.py');
const WORKDIR = '/tmp/epaper_work';
const OUTBOX = '/tmp/epaper_outbox';
// Baqi newspapers finished between 4:30–5:00 AM (either the first pass or a
// retry) get MOVED here so the 15-min retry sweep (which scans OUTBOX) can
// never accidentally send them early. baqiSend() picks them up at 5:00 AM.
const BAQI_STAGING = '/tmp/epaper_baqi_staging';
const TZ_OPTS = { timezone: 'Asia/Karachi' };

fs.ensureDirSync(WORKDIR);
fs.ensureDirSync(OUTBOX);
fs.ensureDirSync(BAQI_STAGING);

let currentSock = null;
let currentSessionId = null;
let cronRegistered = false;

// -----------------------------------------------------------------------------
// TIME HELPERS (Pakistan Standard Time, independent of Heroku dyno's UTC clock)
// -----------------------------------------------------------------------------
function pktNow() {
    return new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Karachi' }));
}
function pktDateStr() {
    const d = pktNow();
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
}

// True once it's 5:00 AM PKT or later -- before that, baqi newspapers must
// NEVER be sent, even if a retry finishes them early.
function baqiSendTimeReached() {
    return pktNow().getHours() >= 5;
}

// Moves a finished (watermarked) PDF + its thumbnail out of OUTBOX into the
// baqi holding area, so the 15-min retry sweep (which only looks at OUTBOX)
// can't send it before its scheduled 5:00 AM slot.
async function moveToStaging(items) {
    const staged = [];
    for (const { key, path: filePath, display } of items) {
        const fileName = path.basename(filePath);
        const thumbPath = filePath.replace(/\.pdf$/i, '.thumb.jpg');
        const destPath = path.join(BAQI_STAGING, fileName);
        const destThumb = destPath.replace(/\.pdf$/i, '.thumb.jpg');
        try {
            await fs.move(filePath, destPath, { overwrite: true });
        } catch (e) {
            console.error(`[epaper] could not stage ${fileName}:`, e.message);
            continue;
        }
        await fs.move(thumbPath, destThumb, { overwrite: true }).catch(() => {});
        staged.push({ key, path: destPath, display });
    }
    return staged;
}

// -----------------------------------------------------------------------------
// PYTHON INVOCATION -- ONE FRESH PROCESS PER NEWSPAPER
// -----------------------------------------------------------------------------
// Deliberately NOT batching multiple newspapers into one long-lived python
// process. Each newspaper gets its own short-lived subprocess that fully
// exits (and hands 100% of its memory back to the OS) before the next one
// starts. On a small 512MB dyno this is the difference between a stable
// run and an R15 (memory quota exceeded) crash.

// Cheap call: just asks python which keys belong to a batch today (respects
// Sunday-only rules) -- does NOT download anything.
function listBatchKeys(batchName) {
    return new Promise((resolve) => {
        const proc = spawn('python3', [SCHEDULER_PY, '--list-batch', batchName], { cwd: SCRIPTS_DIR });
        let stdout = '';
        proc.stdout.on('data', (d) => { stdout += d.toString(); });
        proc.stderr.on('data', (d) => process.stdout.write(`[epaper-py:err] ${d}`));
        proc.on('close', () => {
            const marker = stdout.trim().split('\n').reverse().find((l) => l.startsWith('EPAPER_KEYS_JSON:'));
            if (!marker) return resolve([]);
            try {
                resolve(JSON.parse(marker.slice('EPAPER_KEYS_JSON:'.length)));
            } catch {
                resolve([]);
            }
        });
        proc.on('error', () => resolve([]));
    });
}

// Runs exactly ONE newspaper in its own process, waits for it to fully exit,
// and returns its result.
function runSingleEdition(key) {
    return new Promise((resolve) => {
        const args = ['--editions', key, '--workdir', WORKDIR, '--outdir', OUTBOX];
        console.log(`[epaper] launching (isolated process): python3 epaper_scheduler.py ${args.join(' ')}`);
        const proc = spawn('python3', [SCHEDULER_PY, ...args], { cwd: SCRIPTS_DIR });

        let stdout = '';
        proc.stdout.on('data', (d) => {
            stdout += d.toString();
            process.stdout.write(`[epaper-py] ${d}`);
        });
        proc.stderr.on('data', (d) => process.stdout.write(`[epaper-py:err] ${d}`));

        proc.on('close', () => {
            const marker = stdout.trim().split('\n').reverse().find((l) => l.startsWith('EPAPER_RESULT_JSON:'));
            if (!marker) {
                return resolve({ status: 'failed', display: key, files: [], error: 'no result JSON from python' });
            }
            try {
                const results = JSON.parse(marker.slice('EPAPER_RESULT_JSON:'.length));
                resolve(results[key] || { status: 'failed', display: key, files: [], error: 'missing from result' });
            } catch (e) {
                resolve({ status: 'failed', display: key, files: [], error: `bad JSON: ${e.message}` });
            }
        });
        proc.on('error', (err) => {
            resolve({ status: 'failed', display: key, files: [], error: err.message });
        });
    });
}

// Downloads+watermarks+delivers newspapers ONE AT A TIME: process N must
// fully finish (subprocess exits -> memory freed) AND get handed off via
// onItem (which usually sends it right away) BEFORE process N+1 even starts.
// Slower than parallel, but this is what keeps a 512MB dyno from crashing.
async function runSequentialEditions(keys, onItem) {
    for (const key of keys) {
        const result = await runSingleEdition(key);
        if (onItem) await onItem(key, result);
    }
}

// -----------------------------------------------------------------------------
// WHATSAPP DELIVERY (fresh sendMessage -> never carries a "Forwarded" tag)
// -----------------------------------------------------------------------------
async function sendFiles(items, dateStr) {
    const cfg = await malik_getEpaperConfig(currentSessionId);
    const targets = cfg?.targetJids || [];
    let sentCount = 0;

    for (const { key, path: filePath } of items) {
        const fileName = path.basename(filePath);
        const thumbPath = filePath.replace(/\.pdf$/i, '.thumb.jpg');

        const already = await malik_isEpaperFileSent(currentSessionId, dateStr, fileName);
        if (already) {
            await fs.remove(filePath).catch(() => {});
            await fs.remove(thumbPath).catch(() => {});
            continue;
        }

        if (!targets.length || !currentSock) {
            // No target groups set yet (or bot not connected) -- leave the
            // watermarked file sitting in /tmp so the next send/retry tick
            // can still deliver it instead of losing the work already done.
            continue;
        }

        if (!(await fs.pathExists(filePath))) {
            console.error(`[epaper] file missing, skipping: ${filePath}`);
            continue;
        }

        // Small preview image (few KB) -- fine to hold in memory.
        let jpegThumbnail;
        try {
            jpegThumbnail = await fs.readFile(thumbPath);
        } catch {
            jpegThumbnail = undefined; // no thumbnail generated for this PDF, that's OK
        }

        let anySuccess = false;
        for (const jid of targets) {
            try {
                // { url: <local path> } -> Baileys STREAMS the file straight
                // from disk instead of loading the whole PDF into RAM. On a
                // 512MB Heroku Basic dyno with several newspapers going out
                // in parallel, this keeps memory usage flat instead of
                // stacking up multiple full PDF buffers at once.
                await currentSock.sendMessage(jid, {
                    document: { url: filePath },
                    mimetype: 'application/pdf',
                    fileName,
                    ...(jpegThumbnail ? { jpegThumbnail } : {})
                });
                anySuccess = true;
                await new Promise((r) => setTimeout(r, 700)); // gentle pacing between groups
            } catch (e) {
                console.error(`[epaper] send failed -> ${jid} (${fileName}):`, e.message);
            }
        }

        if (!anySuccess) {
            // Every group failed -- do NOT mark as sent, do NOT delete the
            // file. Leave it in the outbox so the next tick can retry the
            // send without having to re-download/re-watermark anything.
            console.error(`[epaper] all sends failed for ${fileName} — keeping file, will retry`);
            continue;
        }
        await malik_markEpaperFileSent(currentSessionId, dateStr, fileName, key);
        sentCount++;
        // Delete from Heroku /tmp ONLY (never from WhatsApp) -- frees both
        // disk AND the RAM Node/Baileys was using to stream/encrypt it.
        await fs.remove(filePath).catch(() => {});
        await fs.remove(thumbPath).catch(() => {});
    }

    return sentCount;
}

async function queueRetries(batch, keys, dateStr) {
    if (!keys.length) return;
    const cfg = await malik_getEpaperConfig(currentSessionId);
    const existing = (cfg?.pendingRetries || []).map((p) => (p.toObject ? p.toObject() : p));
    for (const key of keys) {
        const exists = existing.find((p) => p.key === key && p.date === dateStr && p.batch === batch);
        if (!exists) existing.push({ batch, key, date: dateStr, attempts: 0 });
    }
    await malik_updateEpaperConfig(currentSessionId, { pendingRetries: existing });
}

// -----------------------------------------------------------------------------
// EXPRESS PIPELINE (single pass: download -> watermark -> send -> delete)
// -----------------------------------------------------------------------------
async function expressRun(force = false) {
    const cfg = await malik_getEpaperConfig(currentSessionId);
    if (!force && !cfg?.enabled) return;

    const dateStr = pktDateStr();
    console.log(`[epaper] 🚀 Express run starting (${dateStr})`);

    const keys = await listBatchKeys('express');
    let sentCount = 0;
    const failedKeys = [];

    await runSequentialEditions(keys, async (key, r) => {
        if (r.status === 'ok' && r.files?.length) {
            const items = r.files.map((f) => ({ key, path: f, display: r.display }));
            sentCount += await sendFiles(items, dateStr); // sent + deleted before the NEXT edition even starts downloading
        } else {
            failedKeys.push(key);
        }
    });

    if (failedKeys.length) await queueRetries('express', failedKeys, dateStr);

    await malik_updateEpaperConfig(currentSessionId, {
        lastRun: new Date(),
        lastRunSummary: `Express: ${sentCount} sent, ${failedKeys.length} queued for retry (${dateStr})`
    });
    console.log(`[epaper] ✅ Express done: ${sentCount} sent, ${failedKeys.length} queued`);
}

// -----------------------------------------------------------------------------
// BAQI PIPELINE (two passes: 4:30 download, 5:00 send)
// -----------------------------------------------------------------------------
async function baqiDownload(force = false) {
    const cfg = await malik_getEpaperConfig(currentSessionId);
    if (!force && !cfg?.enabled) return;

    const dateStr = pktDateStr();
    console.log(`[epaper] 📥 Baqi download starting (${dateStr})`);

    const keys = await listBatchKeys('baqi');
    const allStaged = [];
    const failedKeys = [];

    await runSequentialEditions(keys, async (key, r) => {
        if (r.status === 'ok' && r.files?.length) {
            const items = r.files.map((f) => ({ key, path: f, display: r.display }));
            // Move out of OUTBOX (and thus fully off this process's active
            // working set) immediately, before the next newspaper starts.
            const staged = await moveToStaging(items);
            allStaged.push(...staged);
        } else {
            failedKeys.push(key);
        }
    });

    await malik_updateEpaperConfig(currentSessionId, {
        pendingSendBaqi: allStaged,
        pendingSendDate: dateStr
    });
    if (failedKeys.length) await queueRetries('baqi', failedKeys, dateStr);
    console.log(`[epaper] 📥 Baqi download done: ${allStaged.length} ready (held until 5 AM), ${failedKeys.length} failed`);
}

async function baqiSend(force = false) {
    const cfg = await malik_getEpaperConfig(currentSessionId);
    if (!force && !cfg?.enabled) return;

    const dateStr = pktDateStr();
    const items = cfg?.pendingSendDate === dateStr ? (cfg?.pendingSendBaqi || []) : [];
    console.log(`[epaper] 📤 Baqi send starting: ${items.length} file(s)`);
    const sentCount = await sendFiles(items, dateStr);

    await malik_updateEpaperConfig(currentSessionId, {
        pendingSendBaqi: [],
        lastRun: new Date(),
        lastRunSummary: `Baqi: ${sentCount} sent (${dateStr})`
    });
    console.log(`[epaper] ✅ Baqi send done: ${sentCount} sent`);
}

// Any watermarked PDF that failed to SEND (e.g. wrong/invalid target JID)
// stays in the outbox folder untouched. This resends those on every tick
// without needing to re-download anything.
async function sweepOutbox(dateStr) {
    let files = [];
    try {
        files = await fs.readdir(OUTBOX);
    } catch {
        return 0;
    }
    const pdfs = files.filter((f) => f.toLowerCase().endsWith('.pdf'));
    if (!pdfs.length) return 0;
    const items = pdfs.map((f) => ({ key: 'leftover', path: path.join(OUTBOX, f) }));
    return sendFiles(items, dateStr);
}

// -----------------------------------------------------------------------------
// RETRY TICK (every 15 min — failed newspapers only)
// -----------------------------------------------------------------------------
async function retryTick() {
    const cfg = await malik_getEpaperConfig(currentSessionId);
    if (!cfg?.enabled) return;

    const dateStr = pktDateStr();

    const leftoverSent = await sweepOutbox(dateStr);
    if (leftoverSent) console.log(`[epaper] 📬 Leftover sweep: ${leftoverSent} file(s) delivered`);

    const allPending = (cfg.pendingRetries || []).map((p) => (p.toObject ? p.toObject() : p));
    // NOTE: no attempts cap anymore -- keep retrying a newspaper every 15 min,
    // all day, until it actually succeeds. Once the date rolls over, old
    // (yesterday's) entries simply stop matching and are dropped below.
    const due = allPending.filter((p) => p.date === dateStr);
    if (!due.length) return;

    const keys = [...new Set(due.map((p) => p.key))];
    console.log(`[epaper] 🔁 Retry tick: ${keys.join(', ')}`);

    const holdUntilFive = !baqiSendTimeReached();
    let sentCount = 0;
    const failedKeys = [];
    const heldBaqiItems = [];

    await runSequentialEditions(keys, async (key, r) => {
        if (r.status === 'ok' && r.files?.length) {
            const items = r.files.map((f) => ({ key, path: f, display: r.display }));
            const pendingEntry = due.find((p) => p.key === key);
            const isBaqi = pendingEntry?.batch === 'baqi';

            if (isBaqi && holdUntilFive) {
                // A "baqi" newspaper finished early via retry, but it's
                // still before 5:00 AM -- hold it, don't send yet.
                const staged = await moveToStaging(items);
                heldBaqiItems.push(...staged);
            } else {
                sentCount += await sendFiles(items, dateStr);
            }
        } else {
            failedKeys.push(key);
        }
    });

    if (heldBaqiItems.length) {
        const cfgNow = await malik_getEpaperConfig(currentSessionId);
        const existing = cfgNow?.pendingSendDate === dateStr ? (cfgNow?.pendingSendBaqi || []) : [];
        await malik_updateEpaperConfig(currentSessionId, {
            pendingSendBaqi: [...existing, ...heldBaqiItems],
            pendingSendDate: dateStr
        });
        console.log(`[epaper] 🕠 ${heldBaqiItems.length} baqi file(s) finished early via retry — held until 5:00 AM`);
    }

    const stillFailed = new Set(failedKeys);
    const untouched = allPending.filter((p) => p.date !== dateStr || !keys.includes(p.key));
    const bumped = due
        .filter((p) => stillFailed.has(p.key))
        .map((p) => ({ ...p, attempts: p.attempts + 1 }));

    await malik_updateEpaperConfig(currentSessionId, { pendingRetries: [...untouched, ...bumped] });
    console.log(`[epaper] 🔁 Retry tick done: ${sentCount} sent, ${bumped.length} still pending (will try again in 15 min)`);
}

// -----------------------------------------------------------------------------
// TEST / SELECTIVE RUN (`.af epaper run <key>` — one or a few newspapers only)
// -----------------------------------------------------------------------------
async function runSpecific(keys) {
    const dateStr = pktDateStr();
    console.log(`[epaper] 🧪 Test run for: ${keys.join(', ')}`);

    let sentCount = 0;
    const failedKeys = [];
    const okKeys = [];

    await runSequentialEditions(keys, async (key, r) => {
        if (r.status === 'ok' && r.files?.length) {
            okKeys.push(key);
            const items = r.files.map((f) => ({ key, path: f, display: r.display }));
            sentCount += await sendFiles(items, dateStr);
        } else {
            failedKeys.push(key);
        }
    });

    if (failedKeys.length) await queueRetries('test', failedKeys, dateStr);
    return { sentCount, okKeys, failedKeys };
}

// -----------------------------------------------------------------------------
// MANUAL RUN (`.af epaper run`)
// -----------------------------------------------------------------------------
async function manualRun() {
    console.log('[epaper] 🧑‍💻 Manual run triggered (.af epaper run)');
    await expressRun(true);
    await baqiDownload(true);
    await baqiSend(true);
    await retryTick();
}

// -----------------------------------------------------------------------------
// CRON REGISTRATION
// -----------------------------------------------------------------------------
function scheduleCron() {
    if (cronRegistered) return;
    cronRegistered = true;

    // Express: Mon–Sat 3:00 AM
    cron.schedule('0 3 * * 1-6', () => expressRun(false), TZ_OPTS);
    // Express: Sunday 5:30 AM (baqi goes first on Sundays)
    cron.schedule('30 5 * * 0', () => expressRun(false), TZ_OPTS);

    // Baqi: download every day 4:30 AM, send every day 5:00 AM
    cron.schedule('30 4 * * *', () => baqiDownload(false), TZ_OPTS);
    cron.schedule('0 5 * * *', () => baqiSend(false), TZ_OPTS);

    // Failed-newspaper retries, every 15 min, ALL DAY (3 AM – 11:45 PM PKT).
    // No attempt cap -- a failing newspaper keeps getting retried until it
    // succeeds; the list naturally resets the next day.
    cron.schedule('*/15 3-23 * * *', () => retryTick(), TZ_OPTS);

    console.log('🗞️  Epaper cron registered (Asia/Karachi): Express 3:00 AM (Sun 5:30 AM) | Baqi 4:30/5:00 AM | failed newspapers retried every 15 min all day until they succeed');
}

// -----------------------------------------------------------------------------
// PUBLIC API
// -----------------------------------------------------------------------------
function init(sock, sessionId) {
    currentSock = sock;
    currentSessionId = sessionId;
    scheduleCron();
}

function updateSocket(sock) {
    currentSock = sock; // called again after a reconnect so sends use the fresh socket
}

async function getStatusText(sessionId) {
    const cfg = await malik_getEpaperConfig(sessionId);
    if (!cfg) return '❌ Database not connected — epaper status unavailable.';

    const status = cfg.enabled ? '🟢 ON' : '🔴 OFF';
    const targets = cfg.targetJids?.length ? cfg.targetJids.map((j, i) => `  ${i + 1}. ${j}`).join('\n') : '  None set';
    const pending = (cfg.pendingRetries || []).filter((p) => p.date === pktDateStr());
    const pendingText = pending.length
        ? pending.map((p) => `  • ${p.key} (${p.attempts} attempt${p.attempts === 1 ? '' : 's'} so far, still trying)`).join('\n')
        : '  None';

    let text = `🗞️ *EPAPER AUTO-SYSTEM*\n\n`;
    text += `*Status:* ${status}\n`;
    text += `*Target Groups:*\n${targets}\n\n`;
    text += `*Last Run:* ${cfg.lastRun ? new Date(cfg.lastRun).toLocaleString('en-US', { timeZone: 'Asia/Karachi' }) : 'Never'}\n`;
    text += `*Last Summary:* ${cfg.lastRunSummary || '—'}\n\n`;
    text += `*Pending Retries (today, unlimited until success):*\n${pendingText}\n\n`;
    text += `*Schedule:* Express 3:00 AM (Sun 5:30 AM) • Baqi 4:30/5:00 AM • failed newspapers retried every 15 min all day\n\n`;
    text += `*Commands:*\n`;
    text += `• \`.af epaper set jid1, jid2\` — set target groups\n`;
    text += `• \`.af epaper on/off\` — enable/disable\n`;
    text += `• \`.af epaper run\` — run everything right now\n`;
    text += `• \`.af epaper run <key>\` — test ONE newspaper (e.g. \`.af epaper run jang\`)\n`;
    text += `• \`.af epaper keys\` — list all newspaper keys\n`;
    text += `• \`.af epaper clearsent\` — clear today's "already sent" records (testing)`;

    return text;
}

// Mirrors scripts/epaper_registry.py keys (for `.af epaper keys` reference only)
const EPAPER_KEYS = [
    'express', 'jang', 'jangsundaymagazine', 'thenews', 'dawn', 'asas',
    'nawaiwaqt', 'dailypakistan', 'khabrain', 'naibaat', 'naibaatmagazine',
    'countrynews', 'parliamenttimes', 'sahafat', 'jasarat', 'jehanpakistan',
    'islamk', 'mashriq', 'baithak', 'ghaznavi', 'intekhab', 'kawish',
    'mahasib', 'pakobserver', 'thenation', 'ummat'
];

module.exports = {
    init,
    updateSocket,
    manualRun,
    runSpecific,
    getStatusText,
    EPAPER_KEYS
};
