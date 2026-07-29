require('dotenv').config();

module.exports = {
    sessionId: process.env.SESSION_ID || 'jiftxgtgtbo',
    mongoDbUrl: process.env.MONGODB_URI || process.env.MONGODB_URL || '',
}