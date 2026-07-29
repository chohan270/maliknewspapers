/**
 * ⚡ MALIK MD AUTOFORWARD BOT ⚡
 * Main Entry Point
 * Developed by Mr Malik (ixxmalik)
 */
require('dotenv').config();
const {
    DisconnectReason,
    jidNormalizedUser,
} = require('@whiskeysockets/baileys');
const { Boom } = require('@hapi/boom');
const express = require('express');
const fs = require('fs');
const path = require('path');

const { malik_connectSession, malik_clearSession, malik_requestPairingCode } = require('./maliklib/session');
const { malik_connectDatabase, malik_getGroupSettings, malik_isDbConnected, malik_getGlobalAutoForward, malik_updateGlobalAutoForward } = require('./maliklib/database');
const epaperEngine = require('./maliklib/epaperEngine');
const config = require('./malik');
const qrcode = require('qrcode');

const malik_app = express();
const malik_port = process.env.PORT || 3000;

// -----------------------------------------------------------------------------
// PLUGIN LOADER (Only 4 specific commands)
// -----------------------------------------------------------------------------
const malik_plugins = new Map();

function malik_loadPlugins() {
    const pluginDir = path.join(__dirname, 'malikplugins');
    if (!fs.existsSync(pluginDir)) return;

    // We only want these specific filenames/commands as per user request
    const requested = ['autoforward.js', 'forward.js', 'gjids.js', 'jid.js', 'uptime.js', 'ping.js', 'menu.js'];
    
    for (const file of requested) {
        const filePath = path.join(pluginDir, file);
        if (fs.existsSync(filePath)) {
            try {
                const plugin = require(`./malikplugins/${file}`);
                if (plugin.name) {
                    const name = plugin.name.toLowerCase();
                    malik_plugins.set(name, plugin);
                    if (plugin.aliases && Array.isArray(plugin.aliases)) {
                        plugin.aliases.forEach(alias => malik_plugins.set(alias.toLowerCase(), plugin));
                    }
                }
            } catch (e) {
                console.error(`Failed to load plugin ${file}:`, e.message);
            }
        }
    }
    console.log(`✅ Loaded ${malik_plugins.size} core commands.`);
}

// -----------------------------------------------------------------------------
// TEXT REPLACEMENT & CLEANING CONFIG
// -----------------------------------------------------------------------------
const { processAndCleanMessage, buildRegexList } = require('./maliklib/cleaner');

// -----------------------------------------------------------------------------
// MEDIA TYPE DETECTION (Used by dashboard per-media forwarding switches)
// -----------------------------------------------------------------------------
function malik_getMediaType(messageObj) {
    if (!messageObj) return 'text';
    if (messageObj.imageMessage) return 'image';
    if (messageObj.videoMessage) return 'video';
    if (messageObj.documentMessage) return 'document';
    if (messageObj.stickerMessage) return 'sticker';
    if (messageObj.audioMessage) return 'audio';
    if (messageObj.conversation || messageObj.extendedTextMessage) return 'text';
    // Unwrap view-once containers before falling back to text
    if (messageObj.viewOnceMessageV2?.message) return malik_getMediaType(messageObj.viewOnceMessageV2.message);
    if (messageObj.viewOnceMessage?.message) return malik_getMediaType(messageObj.viewOnceMessage.message);
    return 'text';
}

// -----------------------------------------------------------------------------
// SESSION STATE
// -----------------------------------------------------------------------------
const sessions = new Map();

// Middleware
malik_app.use(express.json());
malik_app.use(express.static(path.join(__dirname, 'public')));

// Keep-Alive Route
malik_app.get('/ping', (req, res) => res.status(200).send('pong'));

// Dashboard APIs
malik_app.get('/api/status', async (req, res) => {
    const sessionId = config.sessionId || 'malik_session';
    const session = sessions.get(sessionId);
    res.json({
        connected: session?.isConnected || false,
        qr: session?.qr || null,
        dbConnected: malik_isDbConnected()
    });
});

malik_app.get('/api/config', async (req, res) => {
    try {
        const sessionId = config.sessionId || 'malik_session';
        const globalCfg = await malik_getGlobalAutoForward(sessionId);
        res.json({
            enabled: globalCfg?.enabled || false,
            sourceJids: globalCfg?.sourceJids || [],
            targetJids: globalCfg?.targetJids || [],
            oldTextRegex: globalCfg?.oldTextRegex || [],
            newText: globalCfg?.newText || "",
            mediaToggles: {
                text: globalCfg?.mediaToggles?.text !== false,
                image: globalCfg?.mediaToggles?.image !== false,
                video: globalCfg?.mediaToggles?.video !== false,
                document: globalCfg?.mediaToggles?.document !== false,
                sticker: globalCfg?.mediaToggles?.sticker !== false,
                audio: globalCfg?.mediaToggles?.audio !== false
            }
        });
    } catch (e) {
        console.error('GET /api/config Error:', e.message);
        res.status(500).json({ error: 'Failed to load config' });
    }
});

malik_app.post('/api/config', async (req, res) => {
    try {
        const sessionId = config.sessionId || 'malik_session';
        const body = req.body || {};

        const sourceJids = Array.isArray(body.sourceJids)
            ? body.sourceJids.map(j => String(j).trim()).filter(Boolean)
            : [];
        const targetJids = Array.isArray(body.targetJids)
            ? body.targetJids.map(j => String(j).trim()).filter(Boolean)
            : [];
        const oldTextRegex = Array.isArray(body.oldTextRegex)
            ? body.oldTextRegex.map(p => String(p).trim()).filter(Boolean)
            : [];
        const newText = typeof body.newText === 'string' ? body.newText : '';

        const mediaToggles = {
            text: body.mediaToggles?.text !== false,
            image: body.mediaToggles?.image !== false,
            video: body.mediaToggles?.video !== false,
            document: body.mediaToggles?.document !== false,
            sticker: body.mediaToggles?.sticker !== false,
            audio: body.mediaToggles?.audio !== false
        };

        const enabled = body.enabled !== false;

        const updated = await malik_updateGlobalAutoForward(sessionId, {
            sourceJids,
            targetJids,
            oldTextRegex,
            newText,
            mediaToggles,
            enabled
        });

        if (!updated) return res.status(500).json({ success: false, error: 'Database not connected' });
        res.json({ success: true });
    } catch (e) {
        console.error('POST /api/config Error:', e.message);
        res.status(500).json({ success: false, error: e.message });
    }
});

// Pairing Code API — alternative to scanning the QR code
malik_app.post('/api/pairing-code', async (req, res) => {
    try {
        const sessionId = config.sessionId || 'malik_session';
        const session = sessions.get(sessionId);
        if (!session || !session.sock) {
            return res.status(400).json({ success: false, error: 'Session not ready yet. Please wait and try again.' });
        }
        const { phoneNumber } = req.body || {};
        const code = await malik_requestPairingCode(session.sock, phoneNumber);
        res.json({ success: true, code });
    } catch (e) {
        console.error('POST /api/pairing-code Error:', e.message);
        res.status(400).json({ success: false, error: e.message });
    }
});

// -----------------------------------------------------------------------------
// SESSION MANAGEMENT
// -----------------------------------------------------------------------------
async function startSession(sessionId) {
    if (sessions.has(sessionId)) {
        const existing = sessions.get(sessionId);
        if (existing.isConnected && existing.sock) return;
        if (existing.sock) {
            existing.sock.ev.removeAllListeners('connection.update');
            existing.sock.end(undefined);
            sessions.delete(sessionId);
        }
    }

    console.log(`🚀 Starting session: ${sessionId}`);
    const sessionState = { sock: null, isConnected: false };
    sessions.set(sessionId, sessionState);

    const { malik_sock, saveCreds } = await malik_connectSession(false, sessionId);
    sessionState.sock = malik_sock;

    // Register listeners immediately to avoid missing events
    console.log(`📡 [${sessionId}] Socket created, listening for events...`);

    malik_sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            try {
                sessionState.qr = await qrcode.toDataURL(qr);
            } catch (e) {
                console.error('Failed to generate QR:', e.message);
            }
        }

        if (connection === 'close') {
            sessionState.isConnected = false;
            sessionState.qr = null;
            const statusCode = (lastDisconnect?.error instanceof Boom) ?
                lastDisconnect.error.output.statusCode : 500;
            const shouldReconnect = statusCode !== DisconnectReason.loggedOut && statusCode !== 440;

            console.log(`Session ${sessionId}: Connection closed, reconnecting: ${shouldReconnect}`);
            if (shouldReconnect) {
                setTimeout(() => startSession(sessionId), 3000);
            } else {
                sessions.delete(sessionId);
                await malik_clearSession(sessionId);
            }
        } else if (connection === 'open') {
            sessionState.isConnected = true;
            sessionState.qr = null;
            console.log(`✅ ${sessionId}: Connected to WhatsApp`);
            try {
                epaperEngine.init(malik_sock, sessionId);
                epaperEngine.updateSocket(malik_sock);
            } catch (e) {
                console.error('[epaper] init error:', e.message);
            }
        }
    });

    malik_sock.ev.on('creds.update', saveCreds);

    // -------------------------------------------------------------------------
    // MESSAGE HANDLER
    // -------------------------------------------------------------------------
    malik_sock.ev.on('messages.upsert', async malik_m => {
        const malik_msg = malik_m.messages[0];
        if (!malik_msg.message) return;

        const malik_origin = malik_msg.key.remoteJid;
        const malik_sender = jidNormalizedUser(malik_msg.key.participant || malik_origin);
        
        const malik_text = malik_msg.message.conversation ||
            malik_msg.message.extendedTextMessage?.text ||
            malik_msg.message.imageMessage?.caption ||
            malik_msg.message.videoMessage?.caption ||
            malik_msg.message.documentMessage?.caption || "";
        
        // 1. GLOBAL AUTO FORWARD LOGIC (Background)
        if (malik_origin.endsWith('@g.us') && !malik_msg.key.fromMe) {
            try {
                const globalCfg = await malik_getGlobalAutoForward(sessionId);
                if (globalCfg?.enabled && globalCfg.sourceJids?.includes(malik_origin) && globalCfg.targetJids?.length > 0) {
                    // Per-media-type forwarding switches (Video/Image/Document/Text/Sticker/Audio) — set from the dashboard
                    const malik_mediaType = malik_getMediaType(malik_msg.message);
                    const malik_toggles = globalCfg.mediaToggles || {};
                    const malik_mediaAllowed = malik_toggles[malik_mediaType] !== false;

                    if (malik_mediaAllowed) {
                        // Dynamic Old-Text-Regex / New-Text replacement, set from the dashboard
                        const malik_dynamicRegex = buildRegexList(globalCfg.oldTextRegex);
                        let relayMsg = processAndCleanMessage(malik_msg.message, {
                            oldTextRegex: malik_dynamicRegex,
                            newText: globalCfg.newText
                        });

                        // Unwrap View Once
                        if (relayMsg.viewOnceMessageV2) relayMsg = relayMsg.viewOnceMessageV2.message;
                        if (relayMsg.viewOnceMessage) relayMsg = relayMsg.viewOnceMessage.message;

                        // Apply timestamp if enabled
                        if (globalCfg.autoForwardTimestamp && relayMsg.conversation) {
                            const time = new Date().toLocaleTimeString();
                            relayMsg.conversation = `${relayMsg.conversation}\n\n_[${time}]_`;
                        }

                        for (const targetJid of globalCfg.targetJids) {
                            try {
                                await malik_sock.relayMessage(targetJid, relayMsg, {
                                    messageId: malik_sock.generateMessageTag()
                                });
                            } catch (err) {
                                console.error(`[GLOBAL-FORWARD] Failed for ${targetJid}:`, err.message);
                            }
                        }
                    }
                }
            } catch (err) { }
        }

        // 2. GROUP-SPECIFIC AUTO FORWARD LOGIC (Background)
        if (malik_origin.endsWith('@g.us') && !malik_msg.key.fromMe) {
            try {
                const groupSettings = await malik_getGroupSettings(sessionId, malik_origin);
                if (groupSettings && groupSettings.autoForward && groupSettings.autoForwardTargets?.length > 0) {
                    let relayMsg = processAndCleanMessage(malik_msg.message);
                    
                    // Unwrap View Once
                    if (relayMsg.viewOnceMessageV2) relayMsg = relayMsg.viewOnceMessageV2.message;
                    if (relayMsg.viewOnceMessage) relayMsg = relayMsg.viewOnceMessage.message;

                    for (const targetJid of groupSettings.autoForwardTargets) {
                        try {
                            await malik_sock.relayMessage(targetJid, relayMsg, {
                                messageId: malik_sock.generateMessageTag()
                            });
                        } catch (err) {
                            console.error(`[AUTO-FORWARD] Failed for ${targetJid}:`, err.message);
                        }
                    }
                }
            } catch (err) { }
        }

        // 3. COMMAND HANDLER
        const prefix = '.'; 
        if (malik_text.trim().startsWith(prefix)) {
            const malik_parts = malik_text.trim().slice(prefix.length).trim().split(/\s+/);
            const malik_cmd_input = malik_parts[0].toLowerCase();
            const malik_args = malik_parts.slice(1);

            if (malik_plugins.has(malik_cmd_input)) {
                const plugin = malik_plugins.get(malik_cmd_input);
                try {
                    // Minimal Context
                    const isGroup = malik_origin.endsWith('@g.us');
                    let malik_isAdmin = false;
                    if (isGroup) {
                        try {
                            const groupMetadata = await malik_sock.groupMetadata(malik_origin);
                            const senderMod = groupMetadata.participants.find(p => jidNormalizedUser(p.id) === malik_sender);
                            malik_isAdmin = (senderMod?.admin === 'admin' || senderMod?.admin === 'superadmin');
                        } catch (e) { }
                    }

                    // For simplicity, we define isOwner as true if it's the bot itself or listed in config
                    const ownerNum = (config.ownerNumber || '').replace(/\D/g, '');
                    const isOwner = malik_msg.key.fromMe || (ownerNum && malik_sender.includes(ownerNum));

                    await plugin.malik_handler(malik_sock, malik_origin, {
                        malik_sender,
                        malik_msg,
                        malik_args,
                        sessionId,
                        malik_text,
                        malik_isGroup: isGroup,
                        malik_isAdmin,
                        malik_isOwner: isOwner,
                        malik_isSudo: isOwner,
                        malik_plugins
                    });
                } catch (err) {
                    console.error(`Error in plugin ${malik_cmd_input}:`, err.message);
                }
            }
        }
    });
}

// -----------------------------------------------------------------------------
// PERIODIC CACHE / GARBAGE CLEANUP (every 5 minutes)
// -----------------------------------------------------------------------------
// This NEVER disconnects the WhatsApp session, NEVER touches the sessions Map,
// and NEVER removes stored sourceJids/targetJids from the database. It only
// clears leftover temp files and nudges garbage collection so the bot keeps
// running fast and light over long uptimes.
const MALIK_CLEANUP_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes
const MALIK_TEMP_DIR = path.join(__dirname, 'temp');
const MALIK_TEMP_FILE_MAX_AGE_MS = 10 * 60 * 1000; // 10 minutes

function malik_performCacheCleanup() {
    try {
        // 1. Clean stale temp files (leftover partial downloads, .part/.ytdl fragments, etc.)
        if (fs.existsSync(MALIK_TEMP_DIR)) {
            const now = Date.now();
            const files = fs.readdirSync(MALIK_TEMP_DIR);
            for (const file of files) {
                try {
                    const filePath = path.join(MALIK_TEMP_DIR, file);
                    const stat = fs.statSync(filePath);
                    if (stat.isFile() && (now - stat.mtimeMs) > MALIK_TEMP_FILE_MAX_AGE_MS) {
                        fs.unlinkSync(filePath);
                    }
                } catch (e) { /* ignore individual file errors */ }
            }
        }

        // 2. Nudge garbage collection if Node was started with --expose-gc
        if (typeof global.gc === 'function') {
            global.gc();
        }

        console.log(`🧹 [Cache Cleanup] Cache & garbage cleaned. Session, SourceJids & TargetJids untouched — bot stays connected and fast.`);
    } catch (e) {
        console.error('Cache Cleanup Error:', e.message);
    }
}

// -----------------------------------------------------------------------------
// MAIN STARTUP
// -----------------------------------------------------------------------------
async function main() {
    // 1. Start Dashboard Server IMMEDIATELY (Prevents Heroku timeout)
    malik_app.listen(malik_port, () => {
        console.log(`🌐 Dashboard running on port ${malik_port}`);
    });

    // 2. Load Core Commands
    malik_loadPlugins();

    // 3. Initialize Bot in Background
    (async () => {
        try {
            // Connect Database
            if (config.mongoDbUrl) {
                const dbResult = await malik_connectDatabase(config.mongoDbUrl);
                if (dbResult) console.log('✅ Database connected');
            }

            // Start default session
            const sessionId = config.sessionId || 'malik_session';
            await startSession(sessionId);

            // 4. Start the 5-minute cache/garbage cleanup loop (session-safe, non-disruptive)
            setInterval(malik_performCacheCleanup, MALIK_CLEANUP_INTERVAL_MS);
        } catch (err) {
            console.error('❌ Initialization Error:', err);
        }
    })();
}

main();
