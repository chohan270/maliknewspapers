const {
    fetchLatestWaWebVersion,
    makeCacheableSignalKeyStore,
    makeWASocket,
    Browsers
} = require('@whiskeysockets/baileys');
const pino = require('pino');
const config = require('../malik');
const { useMongoDBAuthState } = require('./mongoAuth');

async function malik_connectSession(usePairingCode = false, customSessionId = null) {
    // -------------------------------------------------------------------------
    // Use MongoDB Auth State directly
    // This removes the dependency on the local file system which is ephemeral on Heroku.
    // -------------------------------------------------------------------------

    // Support multi-tenancy by using a custom session ID if provided
    const sessionId = customSessionId || config.sessionId || 'malik_session';
    console.log(`🔌 Connecting to session: ${sessionId}`);

    const { state, saveCreds } = await useMongoDBAuthState(sessionId);

    let version;
    try {
        const v = await fetchLatestWaWebVersion();
        version = v.version;
    } catch (e) {
        version = [2, 3000, 1017531287];
    }

    const socketOptions = {
        version,
        logger: pino({ level: 'silent' }),
        printQRInTerminal: false,
        auth: {
            creds: state.creds,
            // Wrap keys with makeCacheableSignalKeyStore for better performance
            keys: makeCacheableSignalKeyStore(state.keys, pino({ level: 'silent' })),
        },
        browser: Browsers.ubuntu('Chrome'),
        generateHighQualityLinkPreview: true,
        syncFullHistory: false,
        retryRequestDelayMs: 5000,
        keepAliveIntervalMs: 10000,
        connectTimeoutMs: 60000,
    };

    const malik_sock = makeWASocket(socketOptions);

    return { malik_sock, saveCreds };
}

/**
 * Request a WhatsApp Pairing Code (alternative to scanning the QR code).
 * Must be called with an active, not-yet-registered socket for the session.
 * Returns the pairing code string (e.g. "ABCD-1234") that the user types
 * into WhatsApp > Linked Devices > Link with phone number.
 */
async function malik_requestPairingCode(malik_sock, phoneNumber) {
    if (!malik_sock) throw new Error('No active session socket to request a pairing code from.');
    if (malik_sock.authState?.creds?.registered) {
        throw new Error('Session is already registered/connected. Pairing code is not needed.');
    }
    const cleanNumber = String(phoneNumber || '').replace(/[^0-9]/g, '');
    if (!cleanNumber || cleanNumber.length < 6) {
        throw new Error('Please provide a valid phone number with country code (digits only).');
    }
    const code = await malik_sock.requestPairingCode(cleanNumber);
    return code;
}

async function malik_clearSession(customSessionId = null) {
    const sessionId = customSessionId || config.sessionId || 'malik_session';
    const { useMongoDBAuthState } = require('./mongoAuth');

    // Instantiate with the specific session ID to get the correct model
    const { clearState } = await useMongoDBAuthState(sessionId);
    if (clearState) {
        await clearState();
        console.log(`🗑️ Session cleared from MongoDB: ${sessionId}`);
    }
}

module.exports = { malik_connectSession, malik_clearSession, malik_requestPairingCode };
