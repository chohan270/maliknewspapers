/**
 * ⚡ MALIK MD AUTOFORWARD BOT — EPAPER AUTOMATION ENGINE ⚡
 *
 * Pipeline (per requirements):
 *   Express : 3:00 AM (Sunday 5:30 AM) -> download -> watermark -> send -> delete /tmp
 *   Baqi    : 4:30 AM download -> 5:00 AM send -> delete /tmp
 *   Failed newspapers only: retried every 15 minutes (up to maxRetries)
 *
 * Node spawns scripts/epaper_scheduler.py (python) to do the actual
 * download + watermark work; this file only handles scheduling,
 * WhatsApp delivery, duplicate-skip and the retry queue.
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
const TZ_OPTS = { timezone: 'Asia/Karachi' };

fs.ensureDirSync(WORKDIR);
fs.ensureDirSync(OUTBOX);

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

// -----------------------------------------------------------------------------
// PYTHON INVOCATION
// -----------------------------------------------------------------------------
function runPython(args) {
    return new Promise((resolve) => {
        console.log(`[epaper] launching: python3 epaper_scheduler.py ${args.join(' ')}`);
        const proc = spawn('python3', [SCHEDULER_PY, ...args], { cwd: SCRIPTS_DIR });

        let stdout = '';
        proc.stdout.on('data', (d) => {
            stdout += d.toString();
            process.stdout.write(`[epaper-py] ${d}`);
        });
        proc.stderr.on('data', (d) => process.stdout.write(`[epaper-py:err] ${d}`));

        proc.on('close', () => {
            const marker = stdout
                .trim()
                .split('\n')
                .reverse()
                .find((l) => l.startsWith('EPAPER_RESULT_JSON:'));
            if (!marker) {
                console.error('[epaper] no result JSON from python scheduler');
                return resolve({});
            }
            try {
                resolve(JSON.parse(marker.slice('EPAPER_RESULT_JSON:'.length)));
            } catch (e) {
                console.error('[epaper] failed to parse result JSON:', e.message);
                resolve({});
            }
        });
        proc.on('error', (err) => {
            console.error('[epaper] failed to launch python:', err.message);
            resolve({});
        });
    });
}

// Same as runPython(), but fires onItem(key, result) THE MOMENT each newspaper
// finishes (python scheduler runs all newspapers in parallel and streams a
// line the instant each one is done) -- so a fast newspaper can be sent to
// WhatsApp immediately, without waiting for slower/failing ones in the same
// batch.
function runPythonStreaming(args, onItem) {
    return new Promise((resolve) => {
        console.log(`[epaper] launching (streaming): python3 epaper_scheduler.py ${args.join(' ')}`);
        const proc = spawn('python3', [SCHEDULER_PY, ...args], { cwd: SCRIPTS_DIR });

        let buffer = '';
        let finalResults = {};

        proc.stdout.on('data', (d) => {
            const text = d.toString();
            process.stdout.write(`[epaper-py] ${text}`);
            buffer += text;
            let idx;
            while ((idx = buffer.indexOf('\n')) !== -1) {
                const line = buffer.slice(0, idx).trim();
                buffer = buffer.slice(idx + 1);
                if (line.startsWith('EPAPER_ITEM_JSON:')) {
                    try {
                        const obj = JSON.parse(line.slice('EPAPER_ITEM_JSON:'.length));
                        if (onItem) onItem(obj.key, obj);
                    } catch (e) {
                        console.error('[epaper] bad item JSON:', e.message);
                    }
                } else if (line.startsWith('EPAPER_RESULT_JSON:')) {
                    try {
                        finalResults = JSON.parse(line.slice('EPAPER_RESULT_JSON:'.length));
                    } catch (e) {
                        console.error('[epaper] bad result JSON:', e.message);
                    }
                }
            }
        });
        proc.stderr.on('data', (d) => process.stdout.write(`[epaper-py:err] ${d}`));

        proc.on('close', () => resolve(finalResults));
        proc.on('error', (err) => {
            console.error('[epaper] failed to launch python:', err.message);
            resolve({});
        });
    });
}

function flattenResults(results) {
    const items = [];
    const failedKeys = [];
    for (const [key, r] of Object.entries(results || {})) {
        if (r.status === 'ok' && r.files?.length) {
            for (const filePath of r.files) items.push({ key, path: filePath, display: r.display });
        } else {
            failedKeys.push(key);
        }
    }
    return { items, failedKeys };
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

        const already = await malik_isEpaperFileSent(currentSessionId, dateStr, fileName);
        if (already) {
            await fs.remove(filePath).catch(() => {});
            continue;
        }

        if (!targets.length || !currentSock) {
            // No target groups set yet (or bot not connected) -- leave the
            // watermarked file sitting in /tmp so the next send/retry tick
            // can still deliver it instead of losing the work already done.
            continue;
        }

        let buffer;
        try {
            buffer = await fs.readFile(filePath);
        } catch (e) {
            console.error(`[epaper] could not read ${filePath}:`, e.message);
            continue;
        }

        for (const jid of targets) {
            try {
                await currentSock.sendMessage(jid, {
                    document: buffer,
                    mimetype: 'application/pdf',
                    fileName
                });
                await new Promise((r) => setTimeout(r, 700)); // gentle pacing between groups
            } catch (e) {
                console.error(`[epaper] send failed -> ${jid} (${fileName}):`, e.message);
            }
        }

        await malik_markEpaperFileSent(currentSessionId, dateStr, fileName, key);
        sentCount++;
        await fs.remove(filePath).catch(() => {}); // delete from Heroku /tmp ONLY, never from WhatsApp
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

    let sentCount = 0;
    const failedKeys = [];
    const sendPromises = [];

    await runPythonStreaming(['--batch', 'express', '--workdir', WORKDIR, '--outdir', OUTBOX], (key, r) => {
        if (r.status === 'ok' && r.files?.length) {
            const items = r.files.map((f) => ({ key, path: f }));
            // Sent the instant it's ready -- doesn't wait for other editions.
            sendPromises.push(
                sendFiles(items, dateStr)
                    .then((n) => { sentCount += n; })
                    .catch((e) => console.error('[epaper] send error:', e.message))
            );
        } else {
            failedKeys.push(key);
        }
    });

    await Promise.allSettled(sendPromises);
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
    const results = await runPython(['--batch', 'baqi', '--workdir', WORKDIR, '--outdir', OUTBOX]);
    const { items, failedKeys } = flattenResults(results);

    await malik_updateEpaperConfig(currentSessionId, {
        pendingSendBaqi: items,
        pendingSendDate: dateStr
    });
    if (failedKeys.length) await queueRetries('baqi', failedKeys, dateStr);
    console.log(`[epaper] 📥 Baqi download done: ${items.length} ready, ${failedKeys.length} failed`);
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

// -----------------------------------------------------------------------------
// RETRY TICK (every 15 min — failed newspapers only)
// -----------------------------------------------------------------------------
async function retryTick() {
    const cfg = await malik_getEpaperConfig(currentSessionId);
    if (!cfg?.enabled) return;

    const dateStr = pktDateStr();
    const allPending = (cfg.pendingRetries || []).map((p) => (p.toObject ? p.toObject() : p));
    // NOTE: no attempts cap anymore -- keep retrying a newspaper every 15 min,
    // all day, until it actually succeeds. Once the date rolls over, old
    // (yesterday's) entries simply stop matching and are dropped below.
    const due = allPending.filter((p) => p.date === dateStr);
    if (!due.length) return;

    const keys = [...new Set(due.map((p) => p.key))];
    console.log(`[epaper] 🔁 Retry tick: ${keys.join(', ')}`);

    let sentCount = 0;
    const failedKeys = [];
    const sendPromises = [];

    await runPythonStreaming(['--editions', ...keys, '--workdir', WORKDIR, '--outdir', OUTBOX], (key, r) => {
        if (r.status === 'ok' && r.files?.length) {
            const items = r.files.map((f) => ({ key, path: f }));
            sendPromises.push(
                sendFiles(items, dateStr)
                    .then((n) => { sentCount += n; })
                    .catch((e) => console.error('[epaper] send error:', e.message))
            );
        } else {
            failedKeys.push(key);
        }
    });
    await Promise.allSettled(sendPromises);

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
    const sendPromises = [];

    await runPythonStreaming(['--editions', ...keys, '--workdir', WORKDIR, '--outdir', OUTBOX], (key, r) => {
        if (r.status === 'ok' && r.files?.length) {
            okKeys.push(key);
            const items = r.files.map((f) => ({ key, path: f }));
            sendPromises.push(
                sendFiles(items, dateStr)
                    .then((n) => { sentCount += n; })
                    .catch((e) => console.error('[epaper] send error:', e.message))
            );
        } else {
            failedKeys.push(key);
        }
    });
    await Promise.allSettled(sendPromises);

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
    text += `• \`.af epaper keys\` — list all newspaper keys`;

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
