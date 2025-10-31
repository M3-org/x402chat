#!/usr/bin/env python3
"""
Consolidated crypto superchat application with FastAPI server, database models, and CLI.
"""

import os
import sys
import json
import time
import asyncio
import hashlib
import logging
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Set, Optional
from datetime import datetime, timedelta

# Third-party imports
import aiohttp
import base58
import httpx
from dotenv import load_dotenv
from fastapi import (
    FastAPI,
    WebSocket,
    WebSocketDisconnect,
    HTTPException,
    Depends,
    Header,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import Column, String, Float, Integer, DateTime, Boolean, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session


class SolanaX402:
    """Custom x402 implementation for Solana using facilitator.x402.rs"""

    def __init__(self, pay_to_address: str, facilitator_url: str):
        self.pay_to_address = pay_to_address
        self.facilitator_url = facilitator_url

    async def verify_payment(self, payment_header: str) -> dict:
        """Verify x402 payment - forward payment proof to facilitator"""
        try:
            # For real x402 clients, just forward the payment proof directly
            # The client should send the complete payment proof structure

            logger.info(
                f"🔍 Forwarding x402 payment to facilitator: {self.facilitator_url}/verify"
            )
            logger.info(f"💳 Payment proof length: {len(payment_header)} chars")
            logger.info(f"🔗 Network: {os.getenv('X402_NETWORK', 'solana')}")

            # Try to parse as JSON first (proper x402 client)
            try:
                payment_data = json.loads(payment_header)
                logger.info(f"📦 Parsed x402 payload: {list(payment_data.keys())}")
            except:
                logger.info(f"📝 Raw payment header: {payment_header[:100]}...")
                # For testing, create minimal structure
                payment_data = {
                    "paymentPayload": payment_header,
                    "paymentRequirements": {
                        "network": os.getenv("X402_NETWORK", "solana"),
                        "price": "$0.01",
                        "payTo": self.pay_to_address,
                        "asset": os.getenv(
                            "USDC_MINT", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
                        ),
                        "description": "Crypto SuperChat donation",
                    },
                }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.facilitator_url}/verify", json=payment_data, timeout=30.0
                )

                logger.info(f"📡 Facilitator response: {response.status_code}")
                logger.info(f"📄 Response: {response.text[:500]}...")

                if response.status_code == 200:
                    return response.json()
                else:
                    return {
                        "valid": False,
                        "error": f"HTTP {response.status_code}: {response.text}",
                    }

        except Exception as e:
            logger.error(f"❌ Facilitator error: {e}")
            return {"valid": False, "error": str(e)}

    async def verify_payment_old(self, payment_header: str) -> dict:
        """Verify x402 payment with Solana facilitator"""
        try:
            async with httpx.AsyncClient() as client:
                # Debug: Log the exact payload we're sending
                payload = {
                    "x402Version": 1,
                    "paymentPayload": {
                        "x402Version": 1,
                        "scheme": "exact",
                        "network": "solana",
                        "payload": {
                            "transaction": payment_header  # Base64-encoded signed transaction
                        },
                    },
                    "paymentRequirements": {
                        "scheme": "exact",
                        "network": "solana",
                        "maxAmountRequired": os.getenv(
                            "X402_MAX_AMOUNT", "10000"
                        ),  # 0.01 USDC
                        "resource": "http://localhost:8765/api/donate",
                        "description": "Crypto SuperChat donation",
                        "mimeType": "application/json",
                        "payTo": self.pay_to_address,
                        "maxTimeoutSeconds": int(os.getenv("X402_TIMEOUT", "60")),
                        "asset": os.getenv(
                            "USDC_MINT", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
                        ),
                        "extra": None,
                    },
                }

                logger.info(f"🔍 Sending to facilitator: {self.facilitator_url}/verify")

                # Format 2: Exact schema from facilitator types.rs
                simple_payload = {
                    "x402Version": 1,
                    "paymentPayload": {
                        "x402Version": 1,
                        "scheme": "exact",
                        "network": "solana",
                        "payload": {"transaction": payment_header},
                    },
                    "paymentRequirements": {
                        "scheme": "exact",
                        "network": "solana",
                        "maxAmountRequired": os.getenv("X402_MAX_AMOUNT", "10000"),
                        "resource": "http://localhost:8765/api/donate",
                        "description": "Crypto SuperChat donation",
                        "mimeType": "application/json",
                        "payTo": self.pay_to_address,
                        "maxTimeoutSeconds": int(os.getenv("X402_TIMEOUT", "60")),
                        "asset": os.getenv(
                            "USDC_MINT", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
                        ),
                        "extra": None,
                    },
                }
                logger.info(f"📦 Payload keys: {list(payload.keys())}")
                logger.info(f"💳 Payment header length: {len(payment_header)} chars")
                logger.info(f"🎯 PayTo: {self.pay_to_address}")

                # Try different payload formats to see which one works

                # Format 1: Our current complex format
                logger.info(f"🧪 Testing Format 1 (complex)...")
                response = await client.post(
                    f"{self.facilitator_url}/verify", json=payload, timeout=30.0
                )
                logger.info(f"📡 Format 1 result: {response.status_code}")

                if response.status_code != 400:
                    return (
                        response.json()
                        if response.status_code == 200
                        else {
                            "valid": False,
                            "error": f"HTTP {response.status_code}: {response.text}",
                        }
                    )

                # Format 2: Simpler format
                logger.info(f"🧪 Testing Format 2 (simple)...")
                logger.info(f"🔧 Simple payload: {simple_payload}")
                response2 = await client.post(
                    f"{self.facilitator_url}/verify", json=simple_payload, timeout=30.0
                )
                logger.info(f"📡 Format 2 result: {response2.status_code}")
                logger.info(f"📄 Format 2 response: {response2.text}")

                if response2.status_code == 200:
                    logger.info("🎉 Format 2 SUCCESS!")
                    return response2.json()
                elif response2.status_code == 422:
                    logger.info("🔍 Format 2 got 422 - checking response details...")
                    # Continue testing other formats even if 422

                # Format 3: Direct transaction only
                logger.info(f"🧪 Testing Format 3 (direct)...")
                response = await client.post(
                    f"{self.facilitator_url}/verify",
                    json={"transaction": payment_header},
                    timeout=30.0,
                )
                logger.info(f"📡 Format 3 result: {response.status_code}")

                if response.status_code != 400:
                    return (
                        response.json()
                        if response.status_code == 200
                        else {
                            "valid": False,
                            "error": f"HTTP {response.status_code}: {response.text}",
                        }
                    )

                # If all formats fail, maybe try different endpoint
                logger.info(f"🧪 Testing different endpoint: /validate...")
                response = await client.post(
                    f"{self.facilitator_url}/validate",
                    json=simple_payload,
                    timeout=30.0,
                )

                logger.info(f"📡 Facilitator response: {response.status_code}")
                logger.info(f"📄 Response text: {response.text[:500]}...")

                if response.status_code == 200:
                    return response.json()
                else:
                    return {
                        "valid": False,
                        "error": f"HTTP {response.status_code}: {response.text}",
                    }
        except Exception as e:
            logger.error(f"❌ Facilitator error: {e}")
            return {"valid": False, "error": str(e)}

    def create_payment_required_response(self, amount: str) -> dict:
        """Create 402 Payment Required response"""
        return {
            "accepts": [
                {
                    "network": os.getenv("X402_NETWORK", "base-sepolia"),
                    "asset": os.getenv(
                        "USDC_MINT", "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
                    ),
                    "payTo": self.pay_to_address,
                    "amount": "0.01",
                    "description": "Crypto SuperChat donation",
                }
            ]
        }


load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ============================================================================
# DATABASE MODELS
# ============================================================================

Base = declarative_base()


class Donation(Base):
    """Donation record with moderation support."""

    __tablename__ = "donations"

    # Primary key - use auto-increment for x402 donations
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Legacy blockchain fields (nullable for backward compatibility)
    signature = Column(String, nullable=True)  # Blockchain signature (legacy)
    sender = Column(String, nullable=True)  # Blockchain address (legacy)

    # x402 donation fields
    sender_name = Column(String(12), nullable=False, default="anon")  # Max 12 chars
    message = Column(String(240), nullable=False, default="")  # Max 240 chars
    amount = Column(Float, nullable=False)
    token_symbol = Column(String, nullable=False, default="USDC")
    payment_proof = Column(String, nullable=True)  # x402 payment receipt

    # Legacy memo field (for backward compatibility)
    memo = Column(String, nullable=True)

    # Timestamps
    timestamp = Column(Integer, nullable=True)  # Legacy blockchain timestamp
    created_at = Column(DateTime, default=datetime.utcnow)

    # Moderation fields
    status = Column(String, default="pending")  # pending, approved, rejected
    moderated_at = Column(DateTime, nullable=True)

    # Payment source tracking
    source = Column(String, default="x402")  # "blockchain" or "x402"

    def to_dict(self):
        return {
            "id": self.id,
            "signature": self.signature,  # Legacy field
            "sender": self.sender,  # Legacy field
            "sender_name": self.sender_name,
            "message": self.message,
            "amount": self.amount,
            "token_symbol": self.token_symbol,
            "payment_proof": self.payment_proof,
            "memo": self.memo or "",  # Legacy field
            "timestamp": self.timestamp,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "status": self.status,
            "moderated_at": (
                self.moderated_at.isoformat() if self.moderated_at else None
            ),
            "source": self.source,
        }


# Database setup
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///donations.db")
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)


def init_db():
    """Create tables."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# CLI DONATION FETCHER
# ============================================================================

# Constants
AI16Z_MINT = "HeLp6NuQkmYB4pYWo2zYs22mESHXPQYzXbB8n4V98jwC"
HELIUS_BASE = "https://api.helius.xyz/v0"
RPC_BASE = "https://mainnet.helius-rpc.com"
MEMO_PID = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"


class DonationFetcher:
    def __init__(self):
        self.api_key = os.getenv("HELIUS_API_KEY")
        self.wallet = os.getenv("WALLET_ADDRESS")
        self.whitelisted = os.getenv("WHITELISTED_TOKENS", "").split(",")

        if not self.api_key or not self.wallet:
            logger.error("❌ Missing HELIUS_API_KEY or WALLET_ADDRESS in .env")
            sys.exit(1)

    def rpc_payload(self, method: str, params: List[Any]) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}

    async def fetch_json(self, session: aiohttp.ClientSession, url: str):
        async with session.get(url, timeout=30) as r:
            r.raise_for_status()
            return await r.json()

    async def find_ata(self, session: aiohttp.ClientSession, wallet: str) -> str | None:
        """Find AI16Z token account (ATA) for wallet."""
        payload = self.rpc_payload(
            "getTokenAccountsByOwner",
            [wallet, {"mint": AI16Z_MINT}, {"encoding": "jsonParsed"}],
        )
        async with session.post(
            f"{RPC_BASE}/?api-key={self.api_key}", json=payload
        ) as r:
            data = await r.json()
        accounts = data.get("result", {}).get("value", [])
        return accounts[0]["pubkey"] if accounts else None

    async def collect_from_address(
        self,
        session: aiohttp.ClientSession,
        address: str,
        since_timestamp: int,
        dest_accounts: Set[str],
    ) -> List[Dict[str, Any]]:
        """Collect transactions from a specific address."""
        base = f"{HELIUS_BASE}/addresses/{address}/transactions?api-key={self.api_key}&limit=100"
        collected = []
        before = None

        while True:
            url = base + (f"&before={before}" if before else "")
            page = await self.fetch_json(session, url)
            if not page:
                break

            for tx in page:
                if tx.get("timestamp", 0) < since_timestamp:
                    return collected

                # Check for token transfers to our destination accounts
                for t in tx.get("tokenTransfers", []):
                    if (
                        t.get("mint") in self.whitelisted
                        and t.get("toUserAccount") in dest_accounts
                    ):
                        collected.append(tx)
                        break

            if not page:
                break
            before = page[-1]["signature"]
            if len(page) < 100:
                break

        return collected

    async def collect_transactions(
        self,
        session: aiohttp.ClientSession,
        since_timestamp: int,
        wallet: str,
        ata: str | None,
    ) -> List[Dict[str, Any]]:
        """Collect all relevant transactions."""
        dest_accounts = {wallet}
        if ata:
            dest_accounts.add(ata)

        addresses = list(dest_accounts)
        tasks = [
            self.collect_from_address(session, addr, since_timestamp, dest_accounts)
            for addr in addresses
        ]
        all_txs = [tx for sub in await asyncio.gather(*tasks) for tx in sub]

        # Remove duplicates
        seen = set()
        unique = []
        for tx in sorted(all_txs, key=lambda x: x.get("timestamp", 0), reverse=True):
            sig = tx["signature"]
            if sig not in seen:
                seen.add(sig)
                unique.append(tx)

        return unique

    def parse_donations(self, txs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Parse transactions into donation records."""
        donations = []

        for tx in txs:
            # Extract memo
            memo = self.extract_memo(tx)

            # Check token transfers
            for transfer in tx.get("tokenTransfers", []):
                if transfer.get("mint") in self.whitelisted and transfer.get(
                    "toUserAccount"
                ) in [self.wallet]:
                    # Get amount - Helius provides tokenAmount already converted
                    amount = transfer.get("tokenAmount", 0)
                    if amount <= 0:
                        continue

                    donation = {
                        "signature": tx["signature"],
                        "sender": transfer.get("fromUserAccount") or tx.get("feePayer"),
                        "amount": float(amount),  # Ensure it's a proper float
                        "token_symbol": self.get_token_symbol(transfer.get("mint")),
                        "memo": memo,
                        "timestamp": tx.get("timestamp", int(time.time())),
                    }
                    donations.append(donation)
                    logger.info(
                        f"💰 {donation['token_symbol']} {donation['amount']:.6f} - {memo or '(no memo)'}"
                    )

        return donations

    def extract_memo(self, tx: Dict[str, Any]) -> str | None:
        """Extract memo using the proven approach from reference script."""
        # First check top-level memo fields
        if memos := tx.get("memos"):
            if isinstance(memos, list) and memos and isinstance(memos[0], str):
                return memos[0].strip()
        if memo := tx.get("memo"):
            return memo.strip()

        # Check instructions for memo program
        for ix in tx.get("instructions", []):
            if ix.get("programId") == MEMO_PID:
                data = ix.get("data", "")
                if data:
                    try:
                        # Try base58 decode first
                        decoded = base58.b58decode(data).decode("utf-8")
                        return decoded.strip()
                    except:
                        # Fallback to raw data
                        return data.strip() or None
        return None

    def get_token_symbol(self, mint):
        """Get token symbol from mint address."""
        symbols = {
            "HeLp6NuQkmYB4pYWo2zYs22mESHXPQYzXbB8n4V98jwC": "AI16Z",
            "So11111111111111111111111111111111111111112": "SOL",
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
        }
        return symbols.get(mint, mint[:8] if mint else "UNKNOWN")

    def save_donation(self, donation_data):
        """Save donation to database."""
        db = SessionLocal()
        try:
            # Check if already exists
            existing = (
                db.query(Donation)
                .filter(Donation.signature == donation_data["signature"])
                .first()
            )

            if existing:
                return False

            # Create new donation record
            donation = Donation(**donation_data)
            db.add(donation)
            db.commit()
            return True
        finally:
            db.close()

    async def sync_all(self, days_back=30):
        """Sync all transactions from the past N days using async approach."""
        logger.info(f"🔄 Syncing donations for past {days_back} days...")
        logger.info(f"🎯 Target wallet: {self.wallet}")
        logger.info(f"🎯 Whitelisted tokens: {self.whitelisted}")

        since_timestamp = int((datetime.now() - timedelta(days=days_back)).timestamp())

        async with aiohttp.ClientSession() as session:
            # Find ATA for AI16Z token
            ata = await self.find_ata(session, self.wallet)
            logger.info(f"🔗 Using wallet: {self.wallet}")
            logger.info(f"🔗 Detected ATA: {ata or 'None found'}")

            # Collect all relevant transactions
            logger.info("📥 Collecting transactions...")
            transactions = await self.collect_transactions(
                session, since_timestamp, self.wallet, ata
            )
            logger.info(f"📊 Found {len(transactions)} relevant transactions")

            # Parse into donations
            donations = self.parse_donations(transactions)
            logger.info(f"💰 Parsed {len(donations)} potential donations")

            # Save to database
            saved_count = 0
            for donation in donations:
                if self.save_donation(donation):
                    saved_count += 1
                    logger.info(
                        f"✅ Saved: {donation['token_symbol']} {donation['amount']:.6f}"
                    )
                else:
                    logger.info(f"♻️ Duplicate: {donation['signature'][:16]}...")

            logger.info(f"\n🎉 Sync complete!")
            logger.info(f"  📊 Transactions processed: {len(transactions)}")
            logger.info(f"  💰 New donations saved: {saved_count}")

            return saved_count


# ============================================================================
# FASTAPI APPLICATION
# ============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    # Startup
    init_db()
    asyncio.create_task(monitor_new_donations())
    logger.info("🚀 Started background donation monitor (manual sync only)")
    yield
    # Shutdown - cleanup if needed
    logger.info("👋 Shutting down...")


app = FastAPI(title="Crypto SuperChat", version="1.0.0", lifespan=lifespan)

# CORS - restricted for security
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://localhost:3000",
        "http://127.0.0.1:8080",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "x-402-payment"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Initialize Solana x402
solana_x402 = SolanaX402(
    pay_to_address=os.getenv("PAY_TO_ADDRESS"),
    facilitator_url=os.getenv("FACILITATOR_URL", "https://facilitator.x402.rs"),
)

# WebSocket connections
overlay_connections: List[WebSocket] = []
dashboard_connections: List[WebSocket] = []


# Request models
class ModerationRequest(BaseModel):
    signature: str


class DonationRequest(BaseModel):
    sender_name: str = "anon"
    message: str = ""
    amount: float = float(
        os.getenv("DEFAULT_DONATION_AMOUNT", "$0.01").replace("$", "")
    )

    class Config:
        json_schema_extra = {
            "example": {"sender_name": "anon", "message": "", "amount": 10.0}
        }


# Global sync status
last_sync_time = None
sync_in_progress = False

# In-memory playing state (fast, ephemeral)
currently_playing = None  # {signature: str, donation_data: dict}


@app.get("/")
async def root():
    """Serve overlay HTML."""
    return FileResponse("static/overlay.html")


@app.get("/dashboard")
async def dashboard():
    """Serve dashboard HTML."""
    return FileResponse("static/dashboard.html")


@app.get("/favicon.ico")
async def favicon():
    """Serve favicon."""
    return FileResponse("static/favicon.svg", media_type="image/svg+xml")


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok"}


@app.get("/api/sync/status")
async def get_sync_status():
    """Get sync status and last sync time."""
    return {
        "last_sync": last_sync_time.isoformat() if last_sync_time else None,
        "syncing": sync_in_progress,
    }


@app.get("/api/events/playing")
async def get_currently_playing():
    """Get currently playing donation."""
    return {
        "playing": currently_playing["signature"] if currently_playing else None,
        "donation": currently_playing["donation_data"] if currently_playing else None,
    }


@app.post("/api/sync")
async def trigger_sync():
    """Manually trigger blockchain sync."""
    global last_sync_time, sync_in_progress

    if sync_in_progress:
        raise HTTPException(status_code=429, detail="Sync already in progress")

    sync_in_progress = True
    try:
        fetcher = DonationFetcher()

        # Sync last 2 hours
        result = await fetcher.sync_all(days_back=0.083)

        last_sync_time = datetime.utcnow()
        return {
            "status": "completed",
            "new_donations": result,
            "synced_at": last_sync_time.isoformat(),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")
    finally:
        sync_in_progress = False


# Moderation API endpoints
@app.get("/api/events/pending")
async def get_pending_donations(db: Session = Depends(get_db)):
    """Get pending donations for moderation."""
    donations = (
        db.query(Donation)
        .filter(Donation.status == "pending")
        .order_by(Donation.timestamp.asc())
        .all()
    )

    return [d.to_dict() for d in donations]


@app.get("/api/events/approved/today")
async def get_approved_today(db: Session = Depends(get_db)):
    """Get donations approved today."""
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    donations = (
        db.query(Donation)
        .filter(Donation.status == "approved", Donation.moderated_at >= today_start)
        .all()
    )

    return [d.to_dict() for d in donations]


@app.get("/api/events/rejected/today")
async def get_rejected_today(db: Session = Depends(get_db)):
    """Get donations rejected today."""
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    donations = (
        db.query(Donation)
        .filter(Donation.status == "rejected", Donation.moderated_at >= today_start)
        .all()
    )

    return [d.to_dict() for d in donations]


@app.post("/api/events/play")
async def play_donation(request: ModerationRequest, db: Session = Depends(get_db)):
    """Start playing a donation (in-memory state)."""
    global currently_playing

    donation = (
        db.query(Donation).filter(Donation.signature == request.signature).first()
    )

    if not donation:
        raise HTTPException(status_code=404, detail="Donation not found")

    if donation.status != "pending":
        raise HTTPException(status_code=400, detail="Donation is not pending")

    # Hide any currently playing donation
    if currently_playing:
        await broadcast_hide_donation(currently_playing["signature"])

    # Set as currently playing (in-memory only)
    currently_playing = {
        "signature": request.signature,
        "donation_data": donation.to_dict(),
    }

    # Broadcast to overlay
    await broadcast_approved_donation(donation.to_dict())

    return {"status": "playing"}


@app.post("/api/events/approve")
async def approve_donation(request: ModerationRequest, db: Session = Depends(get_db)):
    """Approve a playing donation (database update)."""
    global currently_playing

    # Check if this donation is currently playing
    if not currently_playing or currently_playing["signature"] != request.signature:
        raise HTTPException(status_code=400, detail="Donation is not currently playing")

    donation = (
        db.query(Donation).filter(Donation.signature == request.signature).first()
    )

    if not donation:
        raise HTTPException(status_code=404, detail="Donation not found")

    # Update database: pending → approved
    donation.status = "approved"
    donation.moderated_at = datetime.utcnow()
    db.commit()

    # Hide from overlay
    await broadcast_hide_donation(request.signature)

    # Clear playing state
    currently_playing = None

    return {"status": "approved"}


@app.post("/api/events/reject")
async def reject_donation(request: ModerationRequest, db: Session = Depends(get_db)):
    """Reject a donation."""
    donation = (
        db.query(Donation).filter(Donation.signature == request.signature).first()
    )

    if not donation:
        raise HTTPException(status_code=404, detail="Donation not found")

    donation.status = "rejected"
    donation.moderated_at = datetime.utcnow()
    db.commit()

    return {"status": "rejected"}


# x402 Donation API
@app.post("/api/donate")
async def submit_donation(
    request: DonationRequest,
    db: Session = Depends(get_db),
    payment_header: str = Header(None, alias="x-402-payment"),
):
    """Submit donation via x402 payment - private message storage."""

    # Check for payment header
    if not payment_header:
        default_amount = os.getenv("DEFAULT_DONATION_AMOUNT", "$0.01")
        payment_required_response = solana_x402.create_payment_required_response(
            default_amount
        )
        raise HTTPException(status_code=402, detail=payment_required_response)

    # Verify payment with facilitator (temporarily bypassed for debugging)
    logger.info(f"💳 Accepting x402 payment (facilitator bypassed for testing)")
    logger.info(f"Payment proof received: {len(payment_header)} chars")

    # TODO: Re-enable once facilitator issues are resolved
    # payment_result = await solana_x402.verify_payment(payment_header)
    # if not payment_result.get("valid", False):
    #     error_msg = payment_result.get("error", "Invalid payment")
    #     raise HTTPException(status_code=402, detail=f"Payment verification failed: {error_msg}")

    # Mock successful verification for testing
    payment_result = {
        "valid": True,
        "amount": float(os.getenv("DEFAULT_DONATION_AMOUNT", "0.01")),
    }

    # Extract amount from verified payment
    verified_amount = payment_result.get(
        "amount", float(os.getenv("DEFAULT_DONATION_AMOUNT", "$0.01").replace("$", ""))
    )

    # Validate sender name length
    max_name_len = int(os.getenv("MAX_SENDER_NAME_LENGTH", "12"))
    if len(request.sender_name) > max_name_len:
        raise HTTPException(
            status_code=400, detail=f"Sender name too long (max {max_name_len} chars)"
        )

    # Validate message length
    max_msg_len = int(os.getenv("MAX_MESSAGE_LENGTH", "200"))
    if len(request.message) > max_msg_len:
        raise HTTPException(
            status_code=400, detail=f"Message too long (max {max_msg_len} chars)"
        )

    # Create new donation record
    donation = Donation(
        sender_name=request.sender_name[:max_name_len],  # Enforce max length
        message=request.message[:max_msg_len],  # Enforce max length
        amount=verified_amount,  # Use verified payment amount
        token_symbol="USDC",  # x402 uses USDC on Solana
        source="x402",
        created_at=datetime.utcnow(),
        status="pending",
    )

    db.add(donation)
    db.commit()
    db.refresh(donation)

    # Broadcast to dashboard for moderation
    await broadcast_new_donation(donation.to_dict())

    logger.info(
        f"💰 New x402 donation: {donation.sender_name} - ${donation.amount} - {donation.message or '(no message)'}"
    )

    return {
        "status": "success",
        "donation_id": donation.id,
        "message": "Donation submitted for moderation",
    }


# WebSocket endpoints
@app.websocket("/ws")
async def overlay_websocket(websocket: WebSocket):
    """WebSocket for overlay - receives approved donations."""
    await websocket.accept()
    overlay_connections.append(websocket)
    logger.info(f"✅ Overlay connected. Total: {len(overlay_connections)}")

    try:
        await websocket.send_json({"type": "connected"})

        # Keep alive
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        overlay_connections.remove(websocket)
        logger.info(f"❌ Overlay disconnected. Remaining: {len(overlay_connections)}")


@app.websocket("/ws/dashboard")
async def dashboard_websocket(websocket: WebSocket):
    """WebSocket for dashboard - receives new pending donations."""
    await websocket.accept()
    dashboard_connections.append(websocket)
    logger.info(f"✅ Dashboard connected. Total: {len(dashboard_connections)}")

    try:
        await websocket.send_json({"type": "connected"})

        # Keep alive
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        dashboard_connections.remove(websocket)
        logger.info(
            f"❌ Dashboard disconnected. Remaining: {len(dashboard_connections)}"
        )


async def broadcast_to_connections(
    connections: List[WebSocket], message: dict, connection_type: str
) -> None:
    """Generic WebSocket broadcast function - DRY principle."""
    if not connections:
        logger.info(f"📡 No {connection_type} connected for broadcast")
        return

    disconnected = []
    for websocket in connections:
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.info(f"❌ WebSocket send failed: {e}")
            disconnected.append(websocket)

    # Clean up disconnected clients
    for ws in disconnected:
        connections.remove(ws)

    logger.info(f"📡 Broadcasted to {len(connections)} {connection_type}")


async def broadcast_new_donation(donation_data: dict):
    """Broadcast new pending donation to dashboard."""
    message = {"type": "new_donation", "data": donation_data}
    await broadcast_to_connections(dashboard_connections, message, "dashboards")


async def broadcast_approved_donation(donation_data: dict):
    """Broadcast approved donation to overlay."""
    message = {"type": "donation", "data": donation_data}
    await broadcast_to_connections(overlay_connections, message, "overlays")


async def broadcast_hide_donation(signature: str):
    """Broadcast hide donation to overlay."""
    message = {"type": "hide_donation", "signature": signature}
    await broadcast_to_connections(overlay_connections, message, "overlays")


# Background monitoring for new donations
async def monitor_new_donations():
    """Monitor database for new donations and notify dashboard."""
    seen_signatures = set()

    while True:
        db = None
        try:
            db = SessionLocal()
            # Get all pending donations
            pending = db.query(Donation).filter(Donation.status == "pending").all()

            # Check for new ones
            for donation in pending:
                if donation.signature not in seen_signatures:
                    seen_signatures.add(donation.signature)
                    logger.info(
                        f"🚨 New pending donation: {donation.token_symbol} {donation.amount:.6f} - {donation.memo or '(no memo)'}"
                    )
                    await broadcast_new_donation(donation.to_dict())

            await asyncio.sleep(2)  # Check every 2 seconds

        except Exception as e:
            logger.info(f"❌ Monitor error: {e}")
            await asyncio.sleep(5)
        finally:
            if db:
                db.close()


# ============================================================================
# CLI COMMANDS
# ============================================================================


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else None

    if not command:
        logger.info("Usage:")
        logger.info("  python app.py init            # Initialize database")
        logger.info("  python app.py sync [days]     # Sync historical donations")
        logger.info("  python app.py recent          # Show recent donations")
        logger.info("  python app.py server          # Start FastAPI server")
        sys.exit(1)

    if command == "init":
        init_db()
        logger.info("✅ Database initialized")
        return

    if command == "server":
        import uvicorn

        logger.info("🚀 Starting crypto superchat server...")
        logger.info("📂 Overlay: http://localhost:8765/")
        logger.info("🛡️ Dashboard: http://localhost:8765/dashboard")

        port = int(os.getenv("PORT", "8765"))
        uvicorn.run(app, host="0.0.0.0", port=port)
        return

    # For sync/recent commands, use asyncio
    asyncio.run(cli_async(command))


async def cli_async(command):
    # Initialize database if not init command
    init_db()
    fetcher = DonationFetcher()

    if command == "sync":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        await fetcher.sync_all(days_back=days)

    elif command == "recent":
        db = SessionLocal()
        try:
            donations = (
                db.query(Donation).order_by(Donation.timestamp.desc()).limit(10).all()
            )
            logger.info("📋 Recent donations:")
            for d in donations:
                memo_text = f" - {d.memo}" if d.memo else ""
                logger.info(
                    f"  {d.token_symbol} {d.amount:.6f} from {d.sender[:8] if d.sender else 'UNKNOWN'}...{memo_text}"
                )
        finally:
            db.close()

    else:
        logger.info(f"❌ Unknown command: {command}")


if __name__ == "__main__":
    main()
