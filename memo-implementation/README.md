# Memo Implementation - Preserved for Reference

This folder contains the preserved memo-based implementation of the crypto superchat system. This version was working as of August 2025 and is saved here for research and reference purposes.

## What This Is

This is the original memo-based donation system that:
- Monitors Solana blockchain for token transfers with memo fields
- Uses blockchain transaction signatures as primary keys
- Displays blockchain addresses and memo messages
- Syncs with Helius API for real-time transaction monitoring

## Files Structure

```
memo-implementation/
├── app-memo.py          # FastAPI backend focused on memo transactions
├── static/
│   ├── dashboard.html   # Dashboard showing memo-based donations
│   ├── donate.html      # x402 payment form (copied but not used in memo flow)
│   ├── overlay.html     # Overlay for displaying approved donations
│   └── ...
├── donations.db         # Will be created when running memo implementation
└── README.md           # This file
```

## How to Run (For Reference)

```bash
cd memo-implementation

# Install dependencies (same as main app)
pip install -r ../requirements.txt

# Copy environment variables
cp ../.env .env

# Initialize database for memo implementation
python app-memo.py init

# Sync blockchain donations
python app-memo.py sync

# Run memo-focused server
python app-memo.py server
```

## Key Differences from X402 Implementation

### Database Usage
- Uses `signature` as primary identifier for donations
- Focuses on `memo` field for messages
- Shows blockchain `sender` addresses
- Uses blockchain `timestamp` for sorting

### Dashboard Features
- Shows blockchain transaction signatures
- Displays truncated wallet addresses
- Syncs with Helius API for new transactions
- Moderation workflow based on blockchain signatures

### Data Fields
- `signature`: Solana transaction signature (primary key)
- `sender`: Blockchain wallet address  
- `memo`: Message from blockchain memo field
- `timestamp`: Blockchain transaction timestamp
- `amount`: Token amount from blockchain
- `token_symbol`: Token type (AI16Z, SOL, USDC, etc.)

## Status

**Preserved for reference only** - This implementation is not actively maintained.

The main application has moved to x402-based payments for better user experience and production readiness. This memo implementation remains here for:
- Research purposes
- Understanding the original blockchain-based approach  
- Fallback reference if needed
- Learning how memo-based systems work

## Original Documentation

See `/old/CLAUDE.md` for the original comprehensive documentation of this memo-based system.