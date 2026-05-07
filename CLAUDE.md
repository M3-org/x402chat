# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

x402chat is a privacy-aware crypto superchat system for streamers. It enables USDC donations via the x402 protocol on Solana, with Sign-In with Solana (SIWS) wallet authentication. The system emphasizes privacy by performing wallet analysis client-side and storing minimal donor information.

## Development Commands

```bash
# Initial setup
pip install -r requirements.txt
cp .env.example .env
echo ENCRYPTION_KEY=$(openssl rand -base64 32) >> .env

# Initialize database
python app.py init

# Start development server
python app.py server

# Data operations
python app.py recent           # Show 10 most recent donations
python app.py export-json      # Export all donations to JSON
python app.py export-csv       # Export all donations to CSV
```

The server runs on http://localhost:8765 by default (PORT env var).

## Required Environment Variables

- `HELIUS_API_KEY` - Required for Solana RPC and wallet analysis
- `ENCRYPTION_KEY` - Required for encrypting donation messages (base64)
- `PAY_TO_ADDRESS` - Default payment recipient wallet (can be overridden per-user)

## Production Deployment

For production deployments, set these additional environment variables:

- `ENVIRONMENT=production` - Enables strict security policies (CORS, WebSocket origin validation)
- `PRODUCTION_ORIGIN=https://your-domain.com` - Your public-facing domain (required when ENVIRONMENT=production)

Production requirements:
- HTTPS proxy (nginx/Caddy) required for secure cookies
- Set `ENVIRONMENT=production` to enable strict origin validation
- Configure `PRODUCTION_ORIGIN` to match your public domain

## Architecture

### Backend (app.py)
Single consolidated FastAPI application containing:
- **Database Models** (SQLAlchemy + SQLite): `Donation`, `ReceiverId`, `AuthSession`
- **EncryptedString TypeDecorator**: Auto-encrypts/decrypts message fields using Fernet
- **SolanaX402 class**: Handles x402 payment verification directly on-chain (no facilitator dependency)
- **HeliusClient**: Centralized Helius API access with proper error handling
- **Multi-user support**: Each user has receiver_id, username, and separate pay_to_address
- **WebSocket endpoints**: `/ws` for overlay, `/ws/dashboard` for authenticated dashboard updates

### Frontend (static/)
- `index.html/js` - Landing page with SIWS wallet signin
- `wallet-auth.js` - Shared wallet authentication module
- `donate.html/js` - Donation page with privacy check
- `privacy-scorer.js` - Client-side wallet privacy analysis (13 factors)
- `dashboard.html/js` - Moderation dashboard with real-time updates
- `overlay.html` - OBS overlay for displaying approved donations

### Privacy Scorer (privacy_scorer.py)
Standalone module for server-side wallet privacy analysis. Analyzes:
- Token diversity, protocol interactions, NFT holdings
- Transaction patterns (volume, counterparties, dormancy)
- First funding source (Privacy Cash vs CEX origin)

Client-side version (`static/privacy-scorer.js`) mirrors this logic.

## Key Design Decisions

1. **Privacy-first storage**: Donation records do NOT store wallet addresses or transaction signatures. Only date (not time) is stored to prevent timing correlation attacks with blockchain data.

2. **On-chain verification**: Payment verification happens directly against Solana blockchain, not via facilitator service. This eliminates timing/blockhash staleness issues.

3. **Replay attack prevention**: Transaction signatures are tracked in database for 48 hours to prevent double-submission.

4. **Per-user payment addresses**: Users must configure `pay_to_address` separate from their login wallet. Self-donations (same wallet) are blocked.

5. **Session management**: Cookie-based sessions with 7-day expiry for both HTTP endpoints and WebSocket connections.

## API Authentication

Dashboard endpoints require authentication via session cookie. Use `get_current_user(request, db)` helper. WebSocket connections use `verify_websocket_auth(websocket, db)`.

Public endpoints (donation submission, receiver info) authenticate via x402 payment header.

## Testing Notes

Use `http://localhost:8765` (not 0.0.0.0) for Phantom wallet compatibility - it requires secure context.
