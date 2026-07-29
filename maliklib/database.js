const mongoose = require('mongoose');



// SCHEMAS
const malik_toggleSchema = new mongoose.Schema({
    jid: { type: String, required: true },
    command: { type: String, required: true },
    isEnabled: { type: Boolean, default: true }
});

const malik_userSettingsSchema = new mongoose.Schema({
    jid: { type: String, required: true, unique: true },
    autoStatusSeen: { type: Boolean, default: false },
    autoStatusReact: { type: Boolean, default: false },
    autoStatusMessage: { type: Boolean, default: false },
    autoTyping: { type: Boolean, default: false },
    autoRecording: { type: Boolean, default: false },
    autoViewOnce: { type: Boolean, default: false }
});

const malik_autoReplySchema = new mongoose.Schema({
    trigger: { type: String, required: true },
    reply: { type: String, required: true }
});

const malik_rankSchema = new mongoose.Schema({
    jid: { type: String, required: true, unique: true },
    xp: { type: Number, default: 0 },
    level: { type: Number, default: 0 },
    role: { type: String, default: 'Novice' }
});

const malik_sessionIndexSchema = new mongoose.Schema({
    sessionId: { type: String, required: true, unique: true },
    createdAt: { type: Date, default: Date.now }
});

const malik_bgmSchema = new mongoose.Schema({
    trigger: { type: String, required: true },
    audioUrl: { type: String, required: true },
    mimetype: { type: String, default: 'audio/mp4' }
});

const malik_bgmConfigSchema = new mongoose.Schema({
    isEnabled: { type: Boolean, default: true }
});

const malik_mentionSchema = new mongoose.Schema({
    type: { type: String, default: 'text' }, // text, audio, image
    content: { type: String, required: true },
    mimetype: { type: String }
});

const malik_mentionConfigSchema = new mongoose.Schema({
    isEnabled: { type: Boolean, default: true }
});

const malik_botConfigSchema = new mongoose.Schema({
    prefix: { type: String, default: '.' },
    menuImage: { type: String, default: '' },
    autoRead: { type: Boolean, default: false },
    autoRejectCall: { type: Boolean, default: false },
    autoWelcome: { type: Boolean, default: false },
    autoGoodbye: { type: Boolean, default: false },
    welcomeMessage: { type: String, default: '' },
    goodbyeMessage: { type: String, default: '' },
    ownerName: { type: String, default: 'Malik' },
    ownerNumber: { type: String, default: '' },
    ownerJid: { type: String, default: '' },
    sudo: { type: [String], default: [] }, // Array of Sudo JIDs
    autoStatusSeen: { type: Boolean, default: true },
    autoStatusReact: { type: Boolean, default: true },
    autoStatusSave: { type: Boolean, default: false },
    autoStatusEmojis: { type: [String], default: ['❤️', '🧡', '💛', '💚', '💙', '💜', '🌈', '🔥'] }
});

const malik_groupSettingsSchema = new mongoose.Schema({
    jid: { type: String, required: true, unique: true },
    // Antilink settings
    antilink: { type: Boolean, default: false },
    antilinkMode: { type: String, default: 'delete' }, // warn, delete, remove (kick)
    antilinkWarnings: { type: Map, of: Number, default: {} }, // user JID -> warning count
    antilinkMaxWarnings: { type: Number, default: 3 },
    antilinkWhitelist: { type: [String], default: [] }, // Whitelisted link patterns
    // Antidelete settings
    antidelete: { type: Boolean, default: false },
    antideleteDestination: { type: String, default: 'group' }, // group, owner, both
    // AutoForward settings
    autoForward: { type: Boolean, default: false },
    autoForwardTargets: { type: [String], default: [] },
    autoForwardTimestamp: { type: Boolean, default: false },
    autoForwardCaption: { type: String, default: '' },
    autoForwardReplacements: { type: [{ pattern: String, replacement: String }], default: [] },
    // Other settings
    welcome: { type: Boolean, default: false },
    goodbye: { type: Boolean, default: false }
});

const malik_mediaTogglesSchema = new mongoose.Schema({
    text: { type: Boolean, default: true },
    image: { type: Boolean, default: true },
    video: { type: Boolean, default: true },
    document: { type: Boolean, default: true },
    sticker: { type: Boolean, default: true },
    audio: { type: Boolean, default: true }
}, { _id: false });

const malik_globalAutoForwardSchema = new mongoose.Schema({
    enabled: { type: Boolean, default: false },
    sourceJids: { type: [String], default: [] },
    targetJids: { type: [String], default: [] },
    autoForwardTimestamp: { type: Boolean, default: false },
    oldTextRegex: { type: [String], default: [] },
    newText: { type: String, default: '' },
    mediaToggles: { type: malik_mediaTogglesSchema, default: () => ({}) },
    createdAt: { type: Date, default: Date.now }
});

// ---------------------------------------------------------------------------
// EPAPER AUTOMATION SCHEMAS
// ---------------------------------------------------------------------------
const malik_epaperConfigSchema = new mongoose.Schema({
    enabled: { type: Boolean, default: false },
    targetJids: { type: [String], default: [] },
    lastRun: { type: Date, default: null },
    lastRunSummary: { type: String, default: '' },
    // { batch: 'express'|'baqi', key: 'jang', date: 'YYYY-MM-DD', attempts: 1 }
    pendingRetries: { type: [{
        batch: String,
        key: String,
        date: String,
        attempts: { type: Number, default: 0 }
    }], default: [] },
    maxRetries: { type: Number, default: 4 },
    retryDelayMinutes: { type: Number, default: 15 },
    // Watermarked files ready in /tmp between the 4:30 AM "baqi download"
    // pass and the 5:00 AM "baqi send" pass.
    pendingSendBaqi: { type: [{ key: String, path: String, display: String }], default: [] },
    pendingSendDate: { type: String, default: '' }
});

// One row per PDF actually delivered to WhatsApp — used purely to skip
// re-downloading/re-sending the same day's file twice (manual `.af epaper
// run`, retries, dyno restarts, etc. all stay idempotent).
const malik_epaperSentFileSchema = new mongoose.Schema({
    date: { type: String, required: true },     // YYYY-MM-DD (Pakistan time)
    fileName: { type: String, required: true }, // e.g. "Jasarat Karachi 19Jul.pdf"
    key: { type: String, default: '' },          // registry key, e.g. "jasarat"
    sentAt: { type: Date, default: Date.now }
});
malik_epaperSentFileSchema.index({ date: 1, fileName: 1 }, { unique: true });

let isConnected = false;

// ---------------------------------------------------------------------------
// DYNAMIC MODEL HELPER
// ---------------------------------------------------------------------------
function getModel(sessionId, type) {
    const prefix = sessionId || 'malik_session';
    // Use dot notation for collection to get folder view in Compass
    const collectionName = `${prefix}.${type.toLowerCase()}`;
    // Model name can be anything unique
    const modelName = `${prefix}_${type}`;

    if (mongoose.models[modelName]) return mongoose.models[modelName];

    switch (type) {
        case 'Toggle': return mongoose.model(modelName, malik_toggleSchema, collectionName);
        case 'UserSettings': return mongoose.model(modelName, malik_userSettingsSchema, collectionName);
        case 'AutoReply': return mongoose.model(modelName, malik_autoReplySchema, collectionName);
        case 'SessionIndex': return mongoose.model(modelName, malik_sessionIndexSchema, collectionName);
        case 'Bgm': return mongoose.model(modelName, malik_bgmSchema, collectionName);
        case 'BgmConfig': return mongoose.model(modelName, malik_bgmConfigSchema, collectionName);
        case 'Mention': return mongoose.model(modelName, malik_mentionSchema, collectionName);
        case 'MentionConfig': return mongoose.model(modelName, malik_mentionConfigSchema, collectionName);
        case 'BotConfig': return mongoose.model(modelName, malik_botConfigSchema, collectionName);
        case 'GroupSettings': return mongoose.model(modelName, malik_groupSettingsSchema, collectionName);
        case 'GlobalAutoForward': return mongoose.model(modelName, malik_globalAutoForwardSchema, collectionName);
        case 'Rank': return mongoose.model(modelName, malik_rankSchema, collectionName);
        case 'EpaperConfig': return mongoose.model(modelName, malik_epaperConfigSchema, collectionName);
        case 'EpaperSentFile': return mongoose.model(modelName, malik_epaperSentFileSchema, collectionName);
        default: throw new Error(`Unknown model type: ${type}`);
    }
}
// ---------------------------------------------------------------------------
// BOT CONFIG MANAGEMENT
// ---------------------------------------------------------------------------
async function malik_getBotConfig(sessionId) {
    if (!isConnected) return null;
    try {
        const Model = getModel(sessionId, 'BotConfig');
        let config = await Model.findOne({});
        if (!config) {
            config = await Model.create({}); // Create defaults if missing
        }
        return config;
    } catch (e) {
        console.error('DB Error getBotConfig:', e);
        return null;
    }
}

async function malik_updateBotConfig(sessionId, updates) {
    if (!isConnected) return false;
    try {
        const Model = getModel(sessionId, 'BotConfig');
        await Model.findOneAndUpdate({}, updates, { upsert: true, returnDocument: 'after' });
        return true;
    } catch (e) {
        console.error('DB Error updateBotConfig:', e);
        return false;
    }
}



// ---------------------------------------------------------------------------
// DB CONNECTION
// ---------------------------------------------------------------------------
async function malik_connectDatabase(dbUrl) {
    const uri = dbUrl || process.env.MONGODB_URI;

    if (!uri) {
        console.error('❌ FATAL ERROR: No MONGODB_URI found.');
        return false;
    }

    try {
        await mongoose.connect(uri);
        isConnected = true;
        console.log('✅ Malik Bot: Connected to MongoDB successfully!');
        return true;
    } catch (err) {
        console.error('❌ Malik Bot: Failed to connect to MongoDB:', err.message);
        return false;
    }
}

function malik_isDbConnected() {
    return isConnected;
}

// ---------------------------------------------------------------------------
// SESSION MANAGEMENT (Multi-Tenancy)
// ---------------------------------------------------------------------------

async function malik_registerSession(sessionId) {
    if (!isConnected) return false;
    try {
        const Model = getModel(sessionId, 'SessionIndex');
        await Model.findOneAndUpdate(
            { sessionId },
            { sessionId },
            { upsert: true, returnDocument: 'after' }
        );
        return true;
    } catch (e) {
        console.error('DB Error registerSession:', e);
        return false;
    }
}

async function malik_unregisterSession(sessionId) {
    if (!isConnected) return false;
    try {
        const Model = getModel(sessionId, 'SessionIndex');
        await Model.findOneAndDelete({ sessionId });
        return true;
    } catch (e) {
        console.error('DB Error unregisterSession:', e);
        return false;
    }
}

async function malik_getAllSessions(sessionId) {
    if (!isConnected) return [];
    try {
        const Model = getModel(sessionId, 'SessionIndex');
        const sessions = await Model.find({});
        return sessions.map(s => s.sessionId);
    } catch (e) {
        console.error('DB Error getAllSessions:', e);
        return [];
    }
}

// ---------------------------------------------------------------------------
// BGM MANAGEMENT
// ---------------------------------------------------------------------------

async function malik_addBgm(sessionId, trigger, audioUrl, mimetype = 'audio/mp4') {
    if (!isConnected) return false;
    try {
        const Model = getModel(sessionId, 'Bgm');
        await Model.findOneAndUpdate(
            { trigger },
            { trigger, audioUrl, mimetype },
            { upsert: true, returnDocument: 'after' }
        );
        return true;
    } catch (e) {
        console.error('DB Error addBgm:', e);
        return false;
    }
}

async function malik_deleteBgm(sessionId, trigger) {
    if (!isConnected) return false;
    try {
        const Model = getModel(sessionId, 'Bgm');
        const res = await Model.findOneAndDelete({ trigger });
        return !!res;
    } catch (e) {
        console.error('DB Error deleteBgm:', e);
        return false;
    }
}

async function malik_getBgm(sessionId, trigger) {
    if (!isConnected) return null;
    try {
        const Model = getModel(sessionId, 'Bgm');
        const bgm = await Model.findOne({ trigger });
        // Return object structure
        return bgm ? { url: bgm.audioUrl, mimetype: bgm.mimetype || 'audio/mp4' } : null;
    } catch (e) {
        console.error('DB Error getBgm:', e);
        return null;
    }
}

async function malik_getAllBgms(sessionId) {
    if (!isConnected) return [];
    try {
        const Model = getModel(sessionId, 'Bgm');
        return await Model.find({});
    } catch (e) {
        console.error('DB Error getAllBgms:', e);
        return [];
    }
}

async function malik_toggleBgm(sessionId, status) {
    if (!isConnected) return false;
    try {
        const Model = getModel(sessionId, 'BgmConfig');
        await Model.findOneAndUpdate(
            {},
            { isEnabled: status },
            { upsert: true, returnDocument: 'after' }
        );
        return true;
    } catch (e) {
        console.error('DB Error toggleBgm:', e);
        return false;
    }
}

async function malik_isBgmEnabled(sessionId) {
    if (!isConnected) return false;
    try {
        const Model = getModel(sessionId, 'BgmConfig');
        const conf = await Model.findOne({});
        return conf ? conf.isEnabled : true;
    } catch (e) {
        return false;
    }
}

// ---------------------------------------------------------------------------
// MENTION REPLY MANAGEMENT
// ---------------------------------------------------------------------------

async function malik_setMention(sessionId, data) {
    if (!isConnected) return false;
    try {
        const Model = getModel(sessionId, 'Mention');
        // We only store ONE mention reply setting for simplicity like BGM config
        await Model.deleteMany({});
        await Model.create(data);
        return true;
    } catch (e) {
        console.error('DB Error setMention:', e);
        return false;
    }
}

async function malik_getMention(sessionId) {
    if (!isConnected) return null;
    try {
        const Model = getModel(sessionId, 'Mention');
        return await Model.findOne({});
    } catch (e) {
        return null;
    }
}

async function malik_toggleMention(sessionId, status) {
    if (!isConnected) return false;
    try {
        const Model = getModel(sessionId, 'MentionConfig');
        await Model.findOneAndUpdate({}, { isEnabled: status }, { upsert: true, returnDocument: 'after' });
        return true;
    } catch (e) {
        return false;
    }
}

async function malik_isMentionEnabled(sessionId) {
    if (!isConnected) return false;
    try {
        const Model = getModel(sessionId, 'MentionConfig');
        const conf = await Model.findOne({});
        return conf ? conf.isEnabled : false;
    } catch (e) {
        return false;
    }
}

// ---------------------------------------------------------------------------
// GROUP SETTINGS MANAGEMENT
// ---------------------------------------------------------------------------

async function malik_getGroupSettings(sessionId, jid) {
    if (!isConnected) return null;
    try {
        const Model = getModel(sessionId, 'GroupSettings');
        let settings = await Model.findOne({ jid });
        if (!settings) {
            settings = await Model.create({ jid });
        }
        return settings;
    } catch (e) {
        console.error('DB Error getGroupSettings:', e);
        return null;
    }
}

async function malik_updateGroupSettings(sessionId, jid, updates) {
    if (!isConnected) return false;
    try {
        const Model = getModel(sessionId, 'GroupSettings');
        await Model.findOneAndUpdate({ jid }, updates, { upsert: true, returnDocument: 'after' });
        return true;
    } catch (e) {
        console.error('DB Error updateGroupSettings:', e);
        return false;
    }
}

// ---------------------------------------------------------------------------
// COMMANDS / ETC
// ---------------------------------------------------------------------------

async function malik_isCommandEnabled(sessionId, jid, command) {
    if (!isConnected) return true;
    try {
        const Model = getModel(sessionId, 'Toggle');
        const toggle = await Model.findOne({ jid, command });
        return toggle ? toggle.isEnabled : true;
    } catch (e) {
        console.error('DB Error:', e);
        return true;
    }
}

async function malik_toggleCommand(sessionId, jid, command, status) {
    if (!isConnected) return false;
    try {
        const Model = getModel(sessionId, 'Toggle');
        await Model.findOneAndUpdate(
            { jid, command },
            { isEnabled: status },
            { upsert: true, returnDocument: 'after' }
        );
        return true;
    } catch (e) {
        console.error('DB Error:', e);
        return false;
    }
}

async function malik_getUserAutoStatus(sessionId, jid) {
    if (!isConnected) return null;
    try {
        const Model = getModel(sessionId, 'UserSettings');
        const settings = await Model.findOne({ jid });
        return settings;
    } catch (e) {
        console.error('DB Error:', e);
        return null;
    }
}

async function malik_setUserAutoStatus(sessionId, jid, settings) {
    if (!isConnected) return false;
    try {
        const Model = getModel(sessionId, 'UserSettings');
        await Model.findOneAndUpdate(
            { jid },
            settings,
            { upsert: true, returnDocument: 'after' }
        );
        return true;
    } catch (e) {
        console.error('DB Error:', e);
        return false;
    }
}

async function malik_getAllAutoStatusUsers(sessionId) {
    if (!isConnected) return [];
    try {
        const Model = getModel(sessionId, 'UserSettings');
        const users = await Model.find({ autoStatusSeen: true });
        return users.map(u => u.jid);
    } catch (e) {
        console.error('DB Error:', e);
        return [];
    }
}

async function malik_getAutoReplies(sessionId) {
    if (!isConnected) return [];
    try {
        const Model = getModel(sessionId, 'AutoReply');
        const replies = await Model.find({});
        return replies.map(r => ({ trigger: r.trigger, reply: r.reply }));
    } catch (e) {
        console.error('DB Error:', e);
        return [];
    }
}

async function malik_saveAutoReplies(sessionId, replies) {
    if (!isConnected) return false;
    try {
        const Model = getModel(sessionId, 'AutoReply');
        await Model.deleteMany({}); // Clear existing
        if (replies && replies.length > 0) {
            await Model.insertMany(replies);
        }
        return true;
    } catch (e) {
        console.error('DB Error:', e);
        return false;
    }
}

async function malik_addAutoReply(sessionId, trigger, reply) {
    if (!isConnected) return false;
    try {
        const Model = getModel(sessionId, 'AutoReply');
        await Model.findOneAndUpdate(
            { trigger },
            { trigger, reply },
            { upsert: true, returnDocument: 'after' }
        );
        return true;
    } catch (e) {
        console.error('DB Error addAutoReply:', e);
        return false;
    }
}

async function malik_deleteAutoReply(sessionId, trigger) {
    if (!isConnected) return false;
    try {
        const Model = getModel(sessionId, 'AutoReply');
        await Model.findOneAndDelete({ trigger });
        return true;
    } catch (e) {
        console.error('DB Error deleteAutoReply:', e);
        return false;
    }
}

// ---------------------------------------------------------------------------
// RANK / XP SYSTEM
// ---------------------------------------------------------------------------

async function malik_getXP(sessionId, jid) {
    if (!isConnected) return { xp: 0, level: 0, role: 'Novice' };
    try {
        const Model = getModel(sessionId, 'Rank');
        let user = await Model.findOne({ jid });
        if (!user) user = await Model.create({ jid, xp: 0, level: 0, role: 'Novice' });
        return user;
    } catch (e) {
        console.error('DB Error getXP:', e);
        return { xp: 0, level: 0, role: 'Novice' };
    }
}

async function malik_addXP(sessionId, jid, amount) {
    if (!isConnected) return false;
    try {
        const Model = getModel(sessionId, 'Rank');
        let user = await Model.findOne({ jid });
        if (!user) user = await Model.create({ jid, xp: 0, level: 0 });

        user.xp += amount;
        // Simple Level Up Formula: Level = sqrt(XP / 100)
        // Or XP needed = Level * Level * 100
        const newLevel = Math.floor(Math.sqrt(user.xp / 100));

        let leveledUp = false;
        if (newLevel > user.level) {
            user.level = newLevel;
            leveledUp = true;
            // Update Roles based on Level (Example)
            if (newLevel >= 50) user.role = 'Titan';
            else if (newLevel >= 25) user.role = 'Legend';
            else if (newLevel >= 10) user.role = 'Pro';
            else if (newLevel >= 5) user.role = 'Apprentice';
        }

        await user.save();
        return leveledUp ? newLevel : false;
    } catch (e) {
        console.error('DB Error addXP:', e);
        return false;
    }
}

async function malik_getLeaderboard(sessionId, limit = 10) {
    if (!isConnected) return [];
    try {
        const Model = getModel(sessionId, 'Rank');
        return await Model.find({}).sort({ xp: -1 }).limit(limit);
    } catch (e) {
        return [];
    }
}

// ---------------------------------------------------------------------------
// GLOBAL AUTO-FORWARD MANAGEMENT
// ---------------------------------------------------------------------------

async function malik_getGlobalAutoForward(sessionId) {
    if (!isConnected) return null;
    try {
        const Model = getModel(sessionId, 'GlobalAutoForward');
        let config = await Model.findOne({});
        if (!config) {
            config = await Model.create({ enabled: false, sourceJids: [], targetJids: [] });
        }
        return config;
    } catch (e) {
        console.error('DB Error getGlobalAutoForward:', e);
        return null;
    }
}

async function malik_updateGlobalAutoForward(sessionId, updates) {
    if (!isConnected) return false;
    try {
        const Model = getModel(sessionId, 'GlobalAutoForward');
        await Model.findOneAndUpdate({}, updates, { upsert: true, returnDocument: 'after' });
        return true;
    } catch (e) {
        console.error('DB Error updateGlobalAutoForward:', e);
        return false;
    }
}

// ---------------------------------------------------------------------------
// EPAPER AUTOMATION MANAGEMENT
// ---------------------------------------------------------------------------

async function malik_getEpaperConfig(sessionId) {
    if (!isConnected) return null;
    try {
        const Model = getModel(sessionId, 'EpaperConfig');
        let cfg = await Model.findOne({});
        if (!cfg) cfg = await Model.create({});
        return cfg;
    } catch (e) {
        console.error('DB Error getEpaperConfig:', e);
        return null;
    }
}

async function malik_updateEpaperConfig(sessionId, updates) {
    if (!isConnected) return false;
    try {
        const Model = getModel(sessionId, 'EpaperConfig');
        await Model.findOneAndUpdate({}, updates, { upsert: true, returnDocument: 'after' });
        return true;
    } catch (e) {
        console.error('DB Error updateEpaperConfig:', e);
        return false;
    }
}

async function malik_isEpaperFileSent(sessionId, date, fileName) {
    if (!isConnected) return false;
    try {
        const Model = getModel(sessionId, 'EpaperSentFile');
        const found = await Model.findOne({ date, fileName });
        return !!found;
    } catch (e) {
        console.error('DB Error isEpaperFileSent:', e);
        return false;
    }
}

async function malik_markEpaperFileSent(sessionId, date, fileName, key) {
    if (!isConnected) return false;
    try {
        const Model = getModel(sessionId, 'EpaperSentFile');
        await Model.findOneAndUpdate(
            { date, fileName },
            { date, fileName, key, sentAt: new Date() },
            { upsert: true, returnDocument: 'after' }
        );
        return true;
    } catch (e) {
        // Duplicate key errors are expected/harmless here (race-safe skip)
        if (e.code !== 11000) console.error('DB Error markEpaperFileSent:', e);
        return false;
    }
}

async function malik_clearEpaperSentToday(sessionId, date) {
    if (!isConnected) return 0;
    try {
        const Model = getModel(sessionId, 'EpaperSentFile');
        const res = await Model.deleteMany({ date });
        return res.deletedCount || 0;
    } catch (e) {
        console.error('DB Error clearEpaperSentToday:', e);
        return 0;
    }
}

module.exports = {
    malik_connectDatabase,
    malik_isDbConnected,
    malik_isCommandEnabled,
    malik_toggleCommand,
    malik_getUserAutoStatus,
    malik_setUserAutoStatus,
    malik_getAllAutoStatusUsers,
    malik_getAutoReplies,
    malik_saveAutoReplies,
    malik_addAutoReply,
    malik_deleteAutoReply,
    malik_registerSession,
    malik_unregisterSession,
    malik_getAllSessions,
    malik_addBgm,
    malik_deleteBgm,
    malik_getBgm,
    malik_getAllBgms,
    malik_toggleBgm,
    malik_isBgmEnabled,
    malik_getBotConfig,
    malik_updateBotConfig,
    malik_setMention,
    malik_getMention,
    malik_toggleMention,
    malik_isMentionEnabled,
    malik_getGroupSettings,
    malik_updateGroupSettings,
    malik_getGlobalAutoForward,
    malik_updateGlobalAutoForward,
    malik_getXP,
    malik_addXP,
    malik_getLeaderboard,
    malik_getEpaperConfig,
    malik_updateEpaperConfig,
    malik_isEpaperFileSent,
    malik_markEpaperFileSent,
    malik_clearEpaperSentToday
};
