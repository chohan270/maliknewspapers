/**
 * ⚡ MALIK MD AUTOFORWARD BOT ⚡
 * Ping Command
 * Developed by Mr Malik (ixxmalik)
 */
module.exports = {
    name: 'ping',
    category: 'Information',
    desc: 'Show the bot response speed',
    malik_handler: async (malik_sock, malik_origin, context) => {
        const { malik_msg } = context;
        const start = Date.now();
        
        // 1. Send "Ping..."
        const pingMsg = await malik_sock.sendMessage(malik_origin, { text: 'Ping...' });
        const end = Date.now();
        const responseTime = end - start;

        // 2. Incoming Latency (Optional, depends on sync'd clock)
        const incomingLatency = Math.max(0, Date.now() - (malik_msg.messageTimestamp * 1000));
        
        let report = `*🏓 Pong!* — *${responseTime}ms*\n`;
        report += `📡 *Server Latency:* ${incomingLatency}ms`;

        // Update the message
        await malik_sock.sendMessage(malik_origin, { 
            text: report, 
            edit: pingMsg.key 
        });
    }
};
