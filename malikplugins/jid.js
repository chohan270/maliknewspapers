/**
 * ⚡ MALIK MD AUTOFORWARD BOT ⚡
 * JID Utility
 * Developed by Mr Malik (ixxmalik)
 */
module.exports = {
    name: 'jid',
    category: 'Debug',
    desc: 'Get the JID of the current chat',
    malik_handler: async (malik_sock, malik_sender) => {
        await malik_sock.sendMessage(malik_sender, { text: `${malik_sender}` });
    }
};
