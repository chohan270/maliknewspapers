/**
 * ⚡ MALIK MD AUTOFORWARD BOT ⚡
 * Forward Command
 * Developed by Mr Malik (ixxmalik)
 */
module.exports = {
    name: 'forward',
    aliases: ['f'],
    category: 'Tools',
    desc: 'Forward a replied message to multiple JIDs (private, group, or newsletter)',
    malik_handler: async (malik_sock, malik_sender, context) => {
        const { malik_msg, malik_args } = context;
        const config = require('../malik');

        // 1. Get Quoted Message
        let quoted = malik_msg.message?.extendedTextMessage?.contextInfo?.quotedMessage;
        if (!quoted) {
            return await malik_sock.sendMessage(malik_sender, { text: '❌ Please reply to a message you want to forward.' });
        }

        // 1b. Robust Unwrap & Clean (Handle View Once & regex replacement)
        if (quoted.viewOnceMessageV2) {
            quoted = quoted.viewOnceMessageV2.message;
        } else if (quoted.viewOnceMessage) {
            quoted = quoted.viewOnceMessage.message;
        }

        const { processAndCleanMessage } = require('../maliklib/cleaner');
        quoted = processAndCleanMessage(quoted);

        // 2. Parse Targets
        const inputArgs = malik_args.join(' ');
        if (!inputArgs) {
            const usage = `❌ *Invalid Usage*\n\n` +
                `Provide JIDs separated by commas.\n` +
                `Example: \`.f 123@s.whatsapp.net, 456@g.us, 120363@newsletter\``;
            return await malik_sock.sendMessage(malik_sender, { text: usage });
        }

        const targetJids = inputArgs.split(',').map(j => j.trim()).filter(j => j.length > 0);
        if (targetJids.length === 0) {
            return await malik_sock.sendMessage(malik_sender, { text: '❌ No valid JIDs found.' });
        }

        // 3. Prepare the Forward (No Labels as per user request)
        const mType = Object.keys(quoted).find(k => k.endsWith('Message') || k === 'conversation' || k === 'stickerMessage');
        if (mType && quoted[mType] && typeof quoted[mType] === 'object') {
            // Ensure any existing forwarding labels are stripped
            if (quoted[mType].contextInfo) {
                delete quoted[mType].contextInfo.isForwarded;
                delete quoted[mType].contextInfo.forwardingScore;
                delete quoted[mType].contextInfo.forwardedNewsletterMessageInfo;
                quoted[mType].contextInfo.isForwarded = false;
            }
        }

        // 4. Relay Loop
        let successCount = 0;
        let failCount = 0;
        const failedJids = [];

        for (const jid of targetJids) {
            try {
                let target = jid;
                if (!target.includes('@')) {
                    target = target + '@s.whatsapp.net';
                }

                await malik_sock.relayMessage(target, quoted, {
                    messageId: malik_sock.generateMessageTag()
                });

                successCount++;
                await new Promise(r => setTimeout(r, 800));

            } catch (error) {
                console.error(`Relay failed for ${jid}:`, error.message);
                failCount++;
                failedJids.push(jid);
            }
        }

        // 5. Final Report (صرف فیل ہونے پر)
        if (failCount > 0) {
            let report = `⚠️ *کچھ JIDs پر بھیجنا ناکام رہا*\n\n`;
            report += `❌ *Failed:* ${failCount}\n`;
            report += `✨ *Mode:* Native Relay`;
            report += `\n\n*Failed List:*\n${failedJids.map(j => `> ${j}`).join('\n')}`;

            await malik_sock.sendMessage(malik_sender, { text: report });
        }
    }
};
