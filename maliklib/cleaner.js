/**
 * ⚡ MALIK MD AUTOFORWARD BOT ⚡
 * Cleaner Utility
 * Developed by Mr Malik (ixxmalik)
 */
function escapeRegex(string) {
    return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); 
}

const OLD_TEXT_REGEX = process.env.OLD_TEXT_REGEX
    ? process.env.OLD_TEXT_REGEX.split(',').map(pattern => {
        try {
            if (!pattern.trim()) return null;
            // Escape literal text to prevent crash from characters like ( ) [ ] * +
            const escaped = escapeRegex(pattern.trim());
            // Use 'u' flag for better unicode/stylish font support
            return new RegExp(escaped, 'gu');
        } catch (e) {
            console.error(`Invalid regex pattern: ${pattern}`, e);
            return null;
        }
      }).filter(regex => regex !== null)
    : [];

const NEW_TEXT = process.env.NEW_TEXT || '';

/**
 * Build a list of RegExp objects from an array of plain-text patterns.
 * Used to convert dashboard-supplied "Old Text Regex" strings (dynamic,
 * stored in MongoDB) into safe, escaped RegExp instances at runtime.
 */
function buildRegexList(patterns) {
    if (!patterns || !Array.isArray(patterns) || !patterns.length) return [];
    return patterns.map(pattern => {
        try {
            if (!pattern || !pattern.trim()) return null;
            const escaped = escapeRegex(pattern.trim());
            return new RegExp(escaped, 'gu');
        } catch (e) {
            console.error(`Invalid regex pattern: ${pattern}`, e);
            return null;
        }
    }).filter(regex => regex !== null);
}

/**
 * Clean forwarded label and newsletter markers.
 * @param {object} message - The raw baileys message object to clean.
 * @param {object} [options] - Optional dynamic overrides.
 * @param {RegExp[]} [options.oldTextRegex] - Dynamic regex list (from dashboard/DB). Falls back to OLD_TEXT_REGEX env if not provided.
 * @param {string} [options.newText] - Dynamic replacement text (from dashboard/DB). Falls back to NEW_TEXT env if not provided.
 */
function processAndCleanMessage(message, options = {}) {
    try {
        if (!message) return message;
        let cleaned = JSON.parse(JSON.stringify(message));
        
        // Remove all forwarding/newsletter/ad metadata
        const targetBlocks = ['extendedTextMessage', 'imageMessage', 'videoMessage', 'audioMessage', 'documentMessage'];
        targetBlocks.forEach(block => {
            if (cleaned[block]?.contextInfo) {
                // Remove specific forwarding and newsletter labels
                delete cleaned[block].contextInfo.isForwarded;
                delete cleaned[block].contextInfo.forwardingScore;
                delete cleaned[block].contextInfo.forwardedNewsletterMessageInfo;
                delete cleaned[block].contextInfo.externalAdReply;
                delete cleaned[block].contextInfo.newsletterJid;
                delete cleaned[block].contextInfo.newsletterName;
                delete cleaned[block].contextInfo.newsletterServerMessageId;
                
                // Explicitly set to false just in case Baileys defaults to original if missing
                cleaned[block].contextInfo.isForwarded = false;
                cleaned[block].contextInfo.forwardingScore = 0;
            }
            
            // Handle if the block itself has these fields directly (unlikely but safe)
            delete cleaned[block]?.isForwarded;
            delete cleaned[block]?.forwardingScore;
        });

        // Some messages have contextInfo directly on the root under specific structures
        if (cleaned.contextInfo) {
            delete cleaned.contextInfo.isForwarded;
            delete cleaned.contextInfo.forwardingScore;
            delete cleaned.contextInfo.forwardedNewsletterMessageInfo;
            cleaned.contextInfo.isForwarded = false;
        }

        // Replace text/captions — dynamic (dashboard/DB) patterns take priority,
        // falling back to the static env-based patterns if none were supplied.
        const activeRegexList = (options.oldTextRegex && options.oldTextRegex.length)
            ? options.oldTextRegex
            : OLD_TEXT_REGEX;
        const activeNewText = (typeof options.newText === 'string' && options.newText.length)
            ? options.newText
            : NEW_TEXT;

        const replaceText = (text) => {
            if (!text || !activeRegexList.length) return text;
            let result = text;
            activeRegexList.forEach(regex => {
                result = result.replace(regex, activeNewText);
            });
            return result;
        };

        if (cleaned.conversation) cleaned.conversation = replaceText(cleaned.conversation);
        if (cleaned.extendedTextMessage) cleaned.extendedTextMessage.text = replaceText(cleaned.extendedTextMessage.text);
        if (cleaned.imageMessage) cleaned.imageMessage.caption = replaceText(cleaned.imageMessage.caption);
        if (cleaned.videoMessage) cleaned.videoMessage.caption = replaceText(cleaned.videoMessage.caption);
        if (cleaned.documentMessage) cleaned.documentMessage.caption = replaceText(cleaned.documentMessage.caption);

        return cleaned;
    } catch (e) {
        console.error('Cleaning Error:', e.message);
        return message;
    }
}

module.exports = { processAndCleanMessage, buildRegexList };
