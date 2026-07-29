/**
 * ⚡ MALIK MD AUTOFORWARD BOT ⚡
 * Auto-Forward Command with Global Support
 * Developed by Mr Malik (ixxmalik)
 */
const { malik_updateGroupSettings, malik_getGroupSettings, malik_getGlobalAutoForward, malik_updateGlobalAutoForward, malik_getEpaperConfig, malik_updateEpaperConfig } = require('../maliklib/database');
const epaperEngine = require('../maliklib/epaperEngine');

/**
 * Helper: parse a comma-separated list of JIDs and auto-add missing suffixes.
 */
function parseJids(input) {
    return input.split(',').map(j => {
        let jid = j.trim();
        if (!jid) return null;
        if (!jid.includes('@')) {
            jid = jid.includes('-') ? jid + '@g.us' : jid + '@s.whatsapp.net';
        }
        return jid;
    }).filter(Boolean);
}

module.exports = {
    name: 'autoforward',
    description: 'Auto-forward messages from source groups to targets — works even without admin',
    aliases: ['af', 'autof'],
    category: 'Group',
    malik_handler: async (sock, from, context) => {
        const { malik_msg, malik_args, malik_isAdmin, malik_isOwner, malik_isSudo, malik_isGroup, sessionId } = context;

        const action = malik_args[0]?.toLowerCase();
        const sub = malik_args[1]?.toLowerCase();

        // ─────────────────────────────────────────────────────────────────────
        // GLOBAL SET COMMANDS (owner-only)
        // ─────────────────────────────────────────────────────────────────────
        if (action === 'set' && (sub === 'source_jids' || sub === 'target_jids')) {
            if (!malik_isOwner) {
                return await sock.sendMessage(from, { text: '❌ Only the bot owner can set global auto-forward JIDs.' }, { quoted: malik_msg });
            }

            const raw = malik_args.slice(2).join(' ');
            if (!raw) {
                return await sock.sendMessage(from, {
                    text: `❌ Provide JIDs.\nExample:\n.af set ${sub} 12345@g.us, 67890@g.us`
                }, { quoted: malik_msg });
            }

            const jids = parseJids(raw);
            if (!jids.length) {
                return await sock.sendMessage(from, { text: '❌ No valid JIDs found.' }, { quoted: malik_msg });
            }

            const field = sub === 'source_jids' ? 'sourceJids' : 'targetJids';
            await malik_updateGlobalAutoForward(sessionId, { [field]: jids });

            return await sock.sendMessage(from, {
                text: `✅ *Global AutoForward — ${sub} updated*\n\n${jids.map((j, i) => `${i + 1}. ${j}`).join('\n')}`
            }, { quoted: malik_msg });
        }

        // ─────────────────────────────────────────────────────────────────────
        // EPAPER AUTOMATION (owner-only)
        // ─────────────────────────────────────────────────────────────────────
        if (action === 'epaper') {
            if (!malik_isOwner) {
                return await sock.sendMessage(from, { text: '❌ Only the bot owner can manage the epaper system.' }, { quoted: malik_msg });
            }

            if (sub === 'set') {
                const raw = malik_args.slice(2).join(' ');
                if (!raw) {
                    return await sock.sendMessage(from, {
                        text: '❌ Provide target group JIDs.\nExample:\n`.af epaper set 12345@g.us, 67890@g.us`'
                    }, { quoted: malik_msg });
                }
                const jids = parseJids(raw);
                if (!jids.length) {
                    return await sock.sendMessage(from, { text: '❌ No valid JIDs found.' }, { quoted: malik_msg });
                }
                await malik_updateEpaperConfig(sessionId, { targetJids: jids });
                return await sock.sendMessage(from, {
                    text: `✅ *Epaper target groups updated* (${jids.length})\n\n${jids.map((j, i) => `${i + 1}. ${j}`).join('\n')}`
                }, { quoted: malik_msg });
            }

            if (sub === 'on' || sub === 'off') {
                await malik_updateEpaperConfig(sessionId, { enabled: sub === 'on' });
                return await sock.sendMessage(from, { text: `✅ Epaper auto-system *${sub.toUpperCase()}*.` }, { quoted: malik_msg });
            }

            if (sub === 'run') {
                const testKeys = malik_args.slice(2).map((k) => k.toLowerCase()).filter(Boolean);

                if (testKeys.length) {
                    const invalid = testKeys.filter((k) => !epaperEngine.EPAPER_KEYS.includes(k));
                    if (invalid.length) {
                        return await sock.sendMessage(from, {
                            text: `❌ Unknown key(s): ${invalid.join(', ')}\n\nType \`.af epaper keys\` to see the full list.`
                        }, { quoted: malik_msg });
                    }
                    await sock.sendMessage(from, { text: `🧪 Testing: *${testKeys.join(', ')}* — download shuru ho gaya, thora wait karein...` }, { quoted: malik_msg });
                    epaperEngine.runSpecific(testKeys)
                        .then(async ({ sentCount, okKeys, failedKeys }) => {
                            let report = `🧪 *Test Result*\n\n`;
                            if (okKeys.length) report += `✅ Success: ${okKeys.join(', ')}\n`;
                            if (failedKeys.length) report += `❌ Failed: ${failedKeys.join(', ')} (retry queue mein daal diya)\n`;
                            report += `\n📤 Files sent: ${sentCount}`;
                            await sock.sendMessage(from, { text: report }, { quoted: malik_msg }).catch(() => {});
                        })
                        .catch((e) => console.error('[epaper] test run error:', e));
                    return;
                }

                await sock.sendMessage(from, { text: '🚀 Manual epaper run start ho gaya — Express, Baqi aur pending retries sab abhi chalenge. Har newspaper WhatsApp par khud hi aa jayegi jaise ready hogi.' }, { quoted: malik_msg });
                epaperEngine.manualRun().catch((e) => console.error('[epaper] manual run error:', e));
                return;
            }

            if (sub === 'keys') {
                return await sock.sendMessage(from, {
                    text: `📋 *Available Epaper Keys*\n\n${epaperEngine.EPAPER_KEYS.map((k) => `• ${k}`).join('\n')}\n\nExample: \`.af epaper run jang\` or \`.af epaper run jang dawn\``
                }, { quoted: malik_msg });
            }

            // No sub-command -> show status
            const statusText = await epaperEngine.getStatusText(sessionId);
            return await sock.sendMessage(from, { text: statusText }, { quoted: malik_msg });
        }

        // ─────────────────────────────────────────────────────────────────────
        // GLOBAL STATUS & TOGGLE
        // ─────────────────────────────────────────────────────────────────────
        if (action === 'global') {
            if (!malik_isOwner) {
                return await sock.sendMessage(from, { text: '❌ Only the bot owner can manage global auto-forward.' }, { quoted: malik_msg });
            }

            if (sub === 'on' || sub === 'off') {
                await malik_updateGlobalAutoForward(sessionId, { enabled: sub === 'on' });
                return await sock.sendMessage(from, {
                    text: `✅ Global Auto-Forward *${sub.toUpperCase()}*.`
                }, { quoted: malik_msg });
            }

            if (sub === 'timestamp') {
                const state = malik_args[2]?.toLowerCase();
                if (state !== 'on' && state !== 'off') return await sock.sendMessage(from, { text: '❌ Usage: `.af global timestamp on/off`' }, { quoted: malik_msg });
                await malik_updateGlobalAutoForward(sessionId, { autoForwardTimestamp: state === 'on' });
                return await sock.sendMessage(from, { text: `✅ Global Timestamp *${state.toUpperCase()}*.` }, { quoted: malik_msg });
            }

            // Show global status
            const gcfg = await malik_getGlobalAutoForward(sessionId);
            const status = gcfg?.enabled ? '🟢 ON' : '🔴 OFF';
            const tsStatus = gcfg?.autoForwardTimestamp ? '🟢 ON' : '🔴 OFF';
            const srcs = gcfg?.sourceJids?.length ? gcfg.sourceJids.join('\n  ') : 'None';
            const tgts = gcfg?.targetJids?.length ? gcfg.targetJids.join('\n  ') : 'None';

            let text = `📡 *GLOBAL AUTO-FORWARD*\n\n`;
            text += `*Status:* ${status}\n`;
            text += `*Timestamp:* ${tsStatus}\n\n`;
            text += `*Source JIDs* (listen from):\n  ${srcs}\n\n`;
            text += `*Target JIDs* (forward to):\n  ${tgts}\n\n`;
            text += `*Commands:*\n`;
            text += `• \`.af global on/off\` — toggle\n`;
            text += `• \`.af global timestamp on/off\` — toggle time\n`;
            text += `• \`.af set source_jids jid1, jid2\` — set sources\n`;
            text += `• \`.af set target_jids jid1, jid2\` — set targets\n\n`;
            text += `> _This feature works even if the bot is NOT admin in the source group._`;

            return await sock.sendMessage(from, { text }, { quoted: malik_msg });
        }

        // ─────────────────────────────────────────────────────────────────────
        // PER-GROUP COMMANDS
        // ─────────────────────────────────────────────────────────────────────
        if (!action) {
            const globalCfg = await malik_getGlobalAutoForward(sessionId);
            const gStatus = globalCfg?.enabled ? '🟢 ON' : '🔴 OFF';

            let text = `🔄 *AUTO-FORWARD MANAGER*\n\n`;
            text += `📡 *Global Mode:* ${gStatus}\n`;

            if (malik_isGroup) {
                const current = await malik_getGroupSettings(sessionId, from) || {};
                const pStatus = current.autoForward ? '🟢 ON' : '🔴 OFF';
                const targets = current.autoForwardTargets || [];

                text += `\n📌 *This Group:* ${pStatus}\n`;
                text += `🎯 *Targets:* ${targets.length ? targets.join(', ') : 'None'}\n`;
            }

            text += `\n*── COMMON COMMANDS ──*\n`;
            text += `• \`.af on / off\` — Toggle this group\n`;
            text += `• \`.af set jid1, jid2\` — Set targets\n\n`;
            text += `*── ADVANCED OWNER ──*\n`;
            text += `• \`.af global\` — Global settings\n`;
            text += `• \`.af epaper\` — Epaper auto-download system\n`;

            return await sock.sendMessage(from, { text }, { quoted: malik_msg });
        }

        if (!malik_isGroup) {
            return await sock.sendMessage(from, { text: '❌ Use this in a group or use `.af global`.' }, { quoted: malik_msg });
        }

        if (!malik_isAdmin && !malik_isOwner && !malik_isSudo) {
            return await sock.sendMessage(from, { text: '❌ Admin only.' }, { quoted: malik_msg });
        }

        const current = await malik_getGroupSettings(sessionId, from) || {};

        if (action === 'on') {
            if (!current.autoForwardTargets?.length) return await sock.sendMessage(from, { text: '⚠️ Set targets first.' }, { quoted: malik_msg });
            await malik_updateGroupSettings(sessionId, from, { autoForward: true });
            return await sock.sendMessage(from, { text: '✅ *Auto-Forward* enabled.' }, { quoted: malik_msg });
        }

        if (action === 'off') {
            await malik_updateGroupSettings(sessionId, from, { autoForward: false });
            return await sock.sendMessage(from, { text: '✅ *Auto-Forward* disabled.' }, { quoted: malik_msg });
        }

        if (action === 'set') {
            const input = malik_args.slice(1).join(' ');
            if (!input) return await sock.sendMessage(from, { text: '❌ Usage: `.af set jid1, jid2`' }, { quoted: malik_msg });
            const targets = parseJids(input);
            await malik_updateGroupSettings(sessionId, from, { autoForwardTargets: targets });
            return await sock.sendMessage(from, { text: `✅ Targets updated (${targets.length} JIDs).` }, { quoted: malik_msg });
        }

        if (action === 'clear') {
            await malik_updateGroupSettings(sessionId, from, {
                autoForwardTargets: [],
                autoForward: false
            });
            return await sock.sendMessage(from, { text: '✅ All group Auto-Forward settings cleared.' }, { quoted: malik_msg });
        }

        return await sock.sendMessage(from, { text: '❓ Unknown action. Type `.af` for help.' }, { quoted: malik_msg });
    }
};
