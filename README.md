# Crypto SuperChat - Privacy-Aware Tipping on Solana

Privacy-aware crypto superchat for streamers. USDC donations via x402, wallet-based auth (SIWS), client-side privacy scoring.

## 📑 Table of Contents
- [Features](#-features)
- [Development Setup](#-development-setup)
- [Usage](#-usage)
- [Privacy Scoring](#-privacy-scoring)
- [Database Schema](#-database-schema)
- [API Reference](#-api-reference)
- [CLI Commands](#-cli-commands)
- [Troubleshooting](#-troubleshooting)

## ✨ Features

- **💳 X402 Payments** - USDC donations via Phantom, direct blockchain verification
- **🔐 Wallet Auth (SIWS)** - Sign-In with Solana, no passwords, auto-registration
- **🔒 Privacy Scoring** - Client-side analysis (13 factors), wallet addresses never sent to server
- **📊 Quick Privacy Check** - Analyze any Solana wallet without connecting
- **⚠️ Transparent Disclosure** - Shows what's revealed on-chain based on privacy score
- **🛡️ Manual Moderation** - 2-click approval (Play → Approve), dashboard with real-time updates
- **📺 OBS Overlay** - Transparent overlay, typing animations, audio notifications
- **📥 CSV Export** - Full donation data export for analysis
- **🔗 WebSocket Real-time** - Live updates for dashboard and overlay
- **🎓 Educational** - Links to Privacy Cash guides, explains 72-hour rule

---

## 🚀 Development Setup

**Prerequisites**: Python 3.10+, Phantom wallet, Helius API key

```bash
git clone https://github.com/M3-org/x402chat
cd crypto-superchat
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your configuration
echo ENCRYPTION_KEY=$(openssl rand -base64 32) >> .env
python app.py init
python app.py server
```

**First-Time Setup**:
1. Visit `http://localhost:8765/` (use localhost, not 0.0.0.0)
2. Sign in with Phantom → SIWS one-click auth
3. Dashboard → Config tab → Copy donation URL

---

## 🎮 Usage

**For Streamers**: [Dashboard](http://localhost:8765/dashboard) - Review/moderate donations, export CSV, get donation URL

**For Donors**: Visit `/donate/{streamer_id}` - [Example donate page](static/donate.html)

**OBS Overlay**: `http://localhost:8765/overlay` (800x600, enable audio)

## 🔒 Privacy Scoring

Client-side wallet analysis (A-F grade) based on 13 factors. [See implementation](static/privacy-scorer.js)

**Grades**
- A (90+) Excellent 
- B (75-89) Reasonable
- C (60-74) Moderate 
- (40-59) Issues
- F (<40) Poor

**Key**: Wallet addresses analyzed in browser only, never sent to server. Results show what's revealed on-chain.

---

## 📊 Database Schema

```sql
-- Donations: Stores tip data with privacy protections
CREATE TABLE donations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_name VARCHAR(12),               -- Display name
    message VARCHAR(240),                  -- Encrypted
    amount FLOAT NOT NULL,
    payment_proof TEXT,                    -- Encrypted x402 data
    token_symbol VARCHAR DEFAULT 'USDC',
    status VARCHAR DEFAULT 'pending',      -- pending/approved/rejected
    source VARCHAR DEFAULT 'x402',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    moderated_at DATETIME,
);

-- Receiver IDs: Maps wallets to donation page IDs
CREATE TABLE receiver_ids (
    public_key VARCHAR PRIMARY KEY,        -- Solana wallet
    id VARCHAR NOT NULL,                   -- Donation URL ID
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Auth Sessions: Wallet signin sessions
CREATE TABLE auth_session (
    id VARCHAR PRIMARY KEY,                -- Session cookie value
    public_key VARCHAR NOT NULL,           -- Authenticated wallet
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```


## 🔧 API Reference

### Authentication Endpoints

**POST** `/api/auth/wallet-verify`
- Body: `{ publicKey, message, signature, timestamp }`
- Returns: `{ id, publicKey }`
- Creates session cookie automatically

**POST** `/api/auth/challenge` (Legacy)
- Body: `{ publicKey }`
- Returns: `{ message }` - Challenge to sign

**POST** `/api/auth/verify` (Legacy)
- Body: `{ publicKey, message, signature }`
- Returns: `{ id }` with session cookie

### Payment Endpoints

**POST** `/api/donate`
- Headers: `x-402-payment` (x402 payment proof)
- Body: `{ sender_name, message, amount }`
- Returns: `{ donation_id, status }`
- Status: 402 (Payment Required) if no valid payment

### Privacy Endpoints

**POST** `/api/wallet-privacy-score`
- Body: `{ wallet }`
- Returns: `{ score, grade, risks, suggestions, details }`
- Note: Client-side scoring preferred (use `/privacy-scorer.js`)

### Dashboard Endpoints (Authentication Required)

- **GET** `/api/events/pending` - List pending donations
- **GET** `/api/events/approved` - List all approved donations
- **GET** `/api/events/rejected` - List all rejected donations
- **POST** `/api/events/play` - Start playing donation
- **POST** `/api/events/approve` - Approve playing donation
- **POST** `/api/events/reject` - Reject donation
- **POST** `/api/events/restore` - Restore to pending
- **GET** `/api/export/csv` - Export all as CSV
- **GET** `/api/config` - Dashboard config & stats

## 📋 CLI Commands

```bash
# Server Management
python app.py server          # Start FastAPI server on :8765
python app.py init            # Initialize SQLite database

# Data Operations
python app.py recent          # Show 10 most recent donations
python app.py export-json     # Export all to JSON (timestamped backup)
python app.py export-csv      # Export all to CSV (spreadsheet format)
```

## 🏗️ Architecture

```
crypto-superchat/
├── app.py                      # Main FastAPI application
├── privacy_scorer.py           # Server-side privacy scorer (optional)
├── static/
│   ├── index.html/js          # Landing page + SIWS signin
│   ├── wallet-auth.js         # Wallet authentication module (SIWS)
│   ├── donate.html/js/css     # Donation page + privacy check
│   ├── privacy-scorer.js      # Client-side wallet analysis
│   ├── dashboard.html/js/css  # Moderation dashboard
│   ├── overlay.html           # OBS overlay
│   └── global.css             # Shared styles
├── docs/                      # Documentation & research
├── donations.db               # SQLite database
└── .env                       # Configuration (not committed)
```

## 🐛 Troubleshooting

### Phantom Wallet Issues

**Phantom Won't Open**:
- **Cause**: Secure context requirement (Phantom needs https:// or http://localhost)
- **Fix**: Use `http://localhost:8765` NOT `http://0.0.0.0:8765`
- **Note**: Auto-redirect is built-in

**Connection Hangs**:
- Ensure Phantom extension is unlocked
- Try refreshing the Phantom extension
- Check browser console for errors

### Dashboard Issues

**401 Unauthorized**:
- Sign out and sign in again
- Clear browser cache
- Check that session cookie is set

**Pending Donations Not Loading**:
- Verify you're signed in (check sessionStorage for 'walletAuth')
- Check browser console for errors
- Restart server if database was reset

### Privacy Score Issues

**Score Not Loading**:
- Check Helius API key in .env
- Verify wallet address is valid
- Check network connectivity
- See browser console for errors

**Incorrect Wallet Age**:
- Scorer analyzes last 1000 transactions
- If wallet has >1000 txs, age may be approximate
- Power users (≥1000 txs) get instant F grade

### Security Considerations

**HTTPS Required**: Phantom wallet requires secure context in production
**Cookie Security**: Set `secure=True` in production (HTTPS only)
**API Keys**: Never commit .env file
**Database Backups**: Automate daily exports
**Access Control**: Use firewall rules for dashboard access

## 📄 License

TBD

## 🙏 Credits

- [x402 Protocol](https://x402.rs) - Payment protocol for web monetization
- [Privacy Cash](https://privacycash.org) - Privacy-preserving wallet creation
- [Helius](https://helius.dev) - Solana RPC & enhanced APIs
- [Phantom](https://phantom.app) - Solana wallet with SIWS support

---

**Privacy-aware crypto donations for streamers** 🔒

*Sign-In with Solana • Client-Side Privacy • Educational First*
