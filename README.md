# 🤖 MALIK MD AUTOFORWARD BOT 🤖
### Developed by [Mr Malik (ixxmalik)](https://github.com/ixxmalik)

A streamlined, stable, and high-performance WhatsApp bot focused on **Auto-Forwarding** and core utility commands.

---

## 🚀 **CORE FEATURES**
- 🔄 **Auto-Forwarding**: Automatically relay messages from source groups to target chats including channels/newsletters.
- 🧹 **Smart Cleaning**: Automatically removes "Forwarded" labels and "Forwarding Scores".
- ✍️ **Regex Replacement**: Swap text/captions (like removing old links or adding your own footer) on the fly.
- 💾 **Safe Session Management**: Uses MongoDB for persistent auth states, ensuring your bot never logs out.
- ⚡ **Light & Fast**: Stripped of bloated plugins for extreme stability and speed.

---

## 🛠️ **AVAILABLE COMMANDS**
| Command | Alias | Description |
| ------- | ----- | ----------- |
| `.af` | `.autoforward` | Configure auto-forward targets for the current group. |
| `.f` | `.forward` | Manually forward a replied message to multiple JIDs. |
| `.gjids` | | List all your group names and their unique JIDs. |
| `.jid` | | Get the JID of the current chat. |

---

## 💻 **SETUP & DEPLOYMENT**

### **Prerequisites**
- **Node.js 20+**
- **MongoDB Database** (Essential for session stability)

### **Local Installation**
```bash
# Clone the repository
git clone https://github.com/MalikxChaudhary-dev/Malik-Md

# Install dependencies
npm install

# Configure environment variables
# See below for requirements

# Start the bot
npm start
```

---

## ⚙️ **ENVIRONMENT VARIABLES**

| Variable | Description |
| -------- | ----------- |
| `MONGODB_URI` | Your MongoDB connection string. |
| `SESSION_ID` | Custom session name (defaults to `malik_session`). |
| `OLD_TEXT_REGEX` | Comma-separated list of patterns to replace. |
| `NEW_TEXT` | Replacement string (what to put instead of old text). |
| `OWNER_NUMBER` | Your personal WhatsApp number (e.g., `92123456789`). |

---

## ❤️ **CREDITS**
- **Base connection**: [Whiskeysockets Baileys](https://github.com/WhiskeySockets/Baileys)
- **Main Developer**: [Mr Malik (ixxmalik)](https://github.com/ixxmalik)
- **Repo Version**: 1.0.0 (Stable)

---
> _Powered by Mr Malik (ixxmalik)_
