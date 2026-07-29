/**
 * ⚡ MALIK MD AUTOFORWARD BOT ⚡
 * Menu Command
 * Developed by Mr Malik (ixxmalik)
 */
module.exports = {
    name: 'menu',
    aliases: ['help', 'h'],
    category: 'Information',
    desc: 'Show all available commands',
    malik_handler: async (malik_sock, malik_origin, context) => {
        const { malik_plugins, malik_sender } = context;
        
        // Group commands by category (avoiding duplicates from aliases)
        const categories = {};
        const handledCommands = new Set();
        
        for (const [key, plugin] of malik_plugins.entries()) {
            if (handledCommands.has(plugin.name)) continue;
            handledCommands.add(plugin.name);
            
            const category = plugin.category || 'General';
            if (!categories[category]) categories[category] = [];
            categories[category].push(plugin);
        }

        // Build the Menu String
        let menuText = `*⚡ MALIK MD AUTOFORWARD BOT ⚡*\n\n`;
        menuText += `👤 *User:* @${malik_sender.split('@')[0]}\n`;
        menuText += `📜 *Prefix:* .\n`;
        menuText += `🔧 *Commands:* ${handledCommands.size}\n\n`;
        
        for (const category in categories) {
            menuText += `╭───┈ *${category}* ┈───\n`;
            categories[category].forEach(cmd => {
                menuText += `│ ✦ .${cmd.name}\n`;
            });
            menuText += `╰─────────────────\n\n`;
        }
        
        menuText += `> _Developed by Malik x Chaudhary and Mr Malik_`;

        await malik_sock.sendMessage(malik_origin, { 
            text: menuText,
            mentions: [malik_sender]
        });
    }
};
