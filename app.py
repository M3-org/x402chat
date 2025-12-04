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
import csv
import io
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Set, Optional
from datetime import datetime, timedelta

# Third-party imports
import aiohttp
import base58
import httpx
import nacl.exceptions
import nacl.signing
import secrets
from dotenv import load_dotenv
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Header,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import (
    Column,
    String,
    Float,
    Integer,
    DateTime,
    Boolean,
    create_engine,
    TypeDecorator,
    func,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from cryptography.fernet import Fernet
import base64
from solana.rpc.async_api import AsyncClient

# Load environment variables FIRST (before any other initialization)
load_dotenv()

# Import privacy scorer
from privacy_scorer import WalletPrivacyScorer


# ============================================================================
# ENCRYPTION UTILITIES (DRY - Define once, use everywhere)
# ============================================================================


def get_encryption_key() -> bytes:
    """Get encryption key from environment or generate for development"""
    key_b64 = os.getenv("ENCRYPTION_KEY")

    if not key_b64:
        # Development fallback: generate ephemeral key
        # WARNING: This is NOT secure for production - data can't be decrypted after restart
        print("⚠️  No ENCRYPTION_KEY set - using ephemeral key (DEVELOPMENT ONLY)")
        print(
            "    Generate a key: echo ENCRYPTION_KEY=$(openssl rand -base64 32) >> .env"
        )
        return Fernet.generate_key()

    # Fernet expects the key as bytes (the string is already base64 encoded)
    # Just convert the base64 string to bytes, don't decode it
    return key_b64.encode("utf-8")


# Initialize Fernet cipher (singleton, loaded once at startup)
FERNET_CIPHER = Fernet(get_encryption_key())


class EncryptedString(TypeDecorator):
    """
    SQLAlchemy type that automatically encrypts/decrypts strings.

    Usage:
        class MyModel(Base):
            secret_field = Column(EncryptedString(255))

    The field is automatically encrypted when saved and decrypted when retrieved.
    No manual encrypt/decrypt calls needed anywhere in the codebase (DRY principle).
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        """Encrypt on the way INTO the database"""
        if value is None or value == "":
            return None

        try:
            # Fernet.encrypt() returns bytes, convert to UTF-8 string for storage
            encrypted_bytes = FERNET_CIPHER.encrypt(value.encode("utf-8"))
            return encrypted_bytes.decode("utf-8")
        except Exception as e:
            # Log error but don't expose the plaintext
            print(f"❌ Encryption failed: {type(e).__name__}")
            raise

    def process_result_value(self, value, dialect):
        """Decrypt on the way OUT OF the database"""
        if value is None or value == "":
            return None

        try:
            # Fernet.decrypt() expects bytes, convert from UTF-8 string
            decrypted_bytes = FERNET_CIPHER.decrypt(value.encode("utf-8"))
            return decrypted_bytes.decode("utf-8")
        except Exception as e:
            # Handle decryption failures gracefully (wrong key, corrupted data, etc.)
            print(f"❌ Decryption failed: {type(e).__name__}")
            return "[DECRYPTION_FAILED]"


# ============================================================================
# X402 PAYMENT IMPLEMENTATION
# ============================================================================


class SolanaX402:
    """Custom x402 implementation for Solana using facilitator.x402.rs"""

    def __init__(self, pay_to_address: str, facilitator_url: str):
        self.pay_to_address = pay_to_address
        self.facilitator_url = facilitator_url

    async def verify_payment(self, payment_header: str) -> dict:
        """Verify x402 payment with facilitator.x402.rs"""
        import time

        try:
            logger.info(f"🔍 Verifying payment with: {self.facilitator_url}/verify")

            # Parse the payment header (it's a JSON string from client)
            payment_data = json.loads(payment_header)

            # Debug: Log what we're sending
            logger.info(f"📤 Sending to facilitator:")
            logger.info(f"   - x402Version: {payment_data.get('x402Version')}")
            logger.info(
                f"   - paymentPayload.scheme: {payment_data.get('paymentPayload', {}).get('scheme')}"
            )
            logger.info(
                f"   - paymentPayload.network: {payment_data.get('paymentPayload', {}).get('network')}"
            )
            logger.info(
                f"   - paymentRequirements.scheme: {payment_data.get('paymentRequirements', {}).get('scheme')}"
            )
            logger.info(
                f"   - paymentRequirements.maxAmountRequired: {payment_data.get('paymentRequirements', {}).get('maxAmountRequired')}"
            )
            tx_b64 = (
                payment_data.get("paymentPayload", {})
                .get("payload", {})
                .get("transaction", "")
            )
            logger.info(f"   - Transaction length: {len(tx_b64)} chars")

            # Decode transaction to count instructions
            try:
                import base64

                tx_bytes = base64.b64decode(tx_b64)
                logger.info(f"   - Transaction size: {len(tx_bytes)} bytes")
            except Exception as decode_err:
                logger.warning(f"   - Could not decode transaction: {decode_err}")

            async with httpx.AsyncClient() as client:
                # Send the parsed payment data directly (facilitator expects object, not string)
                facilitator_start = time.time()
                response = await client.post(
                    f"{self.facilitator_url}/verify", json=payment_data, timeout=30.0
                )
                facilitator_elapsed = int((time.time() - facilitator_start) * 1000)

                logger.info(
                    f"📡 Facilitator response: {response.status_code} (took {facilitator_elapsed}ms)"
                )

                if response.status_code == 200:
                    result = response.json()
                    is_valid = result.get("isValid") or result.get("valid")

                    if is_valid:
                        logger.info(f"✅ Payment result: VALID")
                        logger.info(f"   - isValid: {result.get('isValid')}")
                        if "amount" in result:
                            logger.info(
                                f"   - amount: {result.get('amount')} (smallest units)"
                            )
                    else:
                        logger.error(f"❌ Payment result: INVALID")
                        logger.error(f"   - isValid: {result.get('isValid')}")
                        logger.error(
                            f"   - invalidReason: {result.get('invalidReason')}"
                        )
                        logger.error(f"   - Full response: {result}")

                    return result
                else:
                    error_text = response.text[:500]  # More chars for debugging
                    logger.error(f"❌ Facilitator HTTP error: {response.status_code}")
                    logger.error(f"   - Response: {error_text}")
                    return {
                        "valid": False,
                        "error": f"HTTP {response.status_code}: {error_text}",
                    }

        except Exception as e:
            logger.error(f"❌ Facilitator exception: {e}")
            logger.error(f"   - Exception type: {type(e).__name__}")
            import traceback

            logger.error(f"   - Traceback: {traceback.format_exc()[:500]}")
            return {"valid": False, "error": str(e)}

    async def verify_transaction_onchain(
        self,
        signature: str,
        expected_recipient: str,
        expected_amount: int,
        expected_asset: str,
    ) -> dict:
        """Verify transaction directly on Solana blockchain (no facilitator needed)

        This replaces facilitator verification with direct on-chain verification.
        Eliminates timing issues with blockhash staleness.
        """
        import time
        from solders.signature import Signature  # type: ignore

        try:
            logger.info("x402.verify_onchain.request: start")
            debug_ctx(
                "x402.verify_onchain.request.ctx",
                signature=signature,
                expected_recipient=expected_recipient,
                expected_amount=expected_amount,
                expected_asset=expected_asset,
            )

            # Connect to Solana RPC (use Helius for reliability)
            # Use "confirmed" commitment to match client-side confirmation
            helius_api_key = os.getenv("HELIUS_API_KEY")
            if not helius_api_key:
                raise ValueError("HELIUS_API_KEY environment variable not set")
            rpc_url = f"https://mainnet.helius-rpc.com/?api-key={helius_api_key}"
            client = AsyncClient(rpc_url, commitment="confirmed")

            # Fetch transaction from blockchain (with retry for RPC sync)
            verify_start = time.time()
            max_retries = 3
            retry_delay = 1.0  # 1 second between retries

            tx_response = None
            for attempt in range(max_retries):
                try:
                    sig_obj = Signature.from_string(signature)
                    # CRITICAL: Must specify max_supported_transaction_version=0
                    # This means "I support up to version 0" which includes V0 versioned transactions
                    # Phantom creates V0 transactions, so we need this!
                    tx_response = await client.get_transaction(
                        sig_obj,
                        encoding="jsonParsed",
                        max_supported_transaction_version=0,  # Required for V0 transactions
                    )

                    if tx_response.value:
                        # Found it!
                        break

                    # Not found yet - RPC nodes might not be synced
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"⚠️  Transaction not found on attempt {attempt + 1}/{max_retries}, retrying in {retry_delay}s..."
                        )
                        await asyncio.sleep(retry_delay)
                    else:
                        logger.error(
                            f"❌ Transaction not found after {max_retries} attempts"
                        )

                except Exception as fetch_error:
                    logger.error(
                        f"❌ Error fetching transaction (attempt {attempt + 1}/{max_retries}): {fetch_error}"
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                    else:
                        raise

            await client.close()

            verify_elapsed = int((time.time() - verify_start) * 1000)
            logger.info(f"x402.verify_onchain.request: rpc_elapsed_ms={verify_elapsed}")

            # Check transaction exists
            if not tx_response or not tx_response.value:
                logger.error(
                    f"x402.verify_onchain.request: not_found retries={max_retries}"
                )
                debug_ctx("x402.verify_onchain.not_found.ctx", signature=signature)
                return {
                    "valid": False,
                    "error": "Transaction not found on blockchain after retries",
                }

            tx = tx_response.value

            # Check transaction succeeded (no errors)
            if tx.transaction.meta.err:
                logger.error(
                    f"x402.verify_onchain.validate: transaction_failed error={tx.transaction.meta.err}"
                )
                return {
                    "valid": False,
                    "error": f"Transaction failed: {tx.transaction.meta.err}",
                }

            logger.info("x402.verify_onchain.validate: transaction_success")

            # Parse instructions to find TransferChecked
            instructions = tx.transaction.transaction.message.instructions
            logger.info(
                f"x402.verify_onchain.validate: instruction_count={len(instructions)}"
            )

            # Find the TransferChecked instruction
            transfer_ix = None
            for idx, ix in enumerate(instructions):
                if hasattr(ix, "parsed"):
                    parsed = ix.parsed
                    if parsed.get("type") == "transferChecked":
                        transfer_ix = parsed
                        logger.info(
                            f"x402.verify_onchain.validate: found_transfer_checked ix={idx}"
                        )
                        break

            if not transfer_ix:
                logger.error("x402.verify_onchain.validate: no_transfer_checked")
                return {
                    "valid": False,
                    "error": "No token transfer found in transaction",
                }

            # Verify transfer details
            info = transfer_ix["info"]

            # 1. Verify token mint (USDC)
            actual_mint = info["mint"]
            if actual_mint != expected_asset:
                logger.error("x402.verify_onchain.validate: token_mismatch")
                debug_ctx(
                    "x402.verify_onchain.validate.ctx",
                    expected_asset=expected_asset,
                    actual_mint=actual_mint,
                )
                return {"valid": False, "error": f"Wrong token: {actual_mint}"}

            logger.info("x402.verify_onchain.validate: token_ok")

            # 2. Verify destination (our USDC ATA)
            actual_destination = info["destination"]
            # Calculate expected ATA
            from spl.token.instructions import get_associated_token_address  # type: ignore
            from solders.pubkey import Pubkey  # type: ignore

            expected_owner = Pubkey.from_string(expected_recipient)
            expected_mint = Pubkey.from_string(expected_asset)
            expected_ata = get_associated_token_address(expected_owner, expected_mint)
            expected_ata_str = str(expected_ata)

            if actual_destination != expected_ata_str:
                logger.error("x402.verify_onchain.validate: recipient_mismatch")
                debug_ctx(
                    "x402.verify_onchain.validate.ctx",
                    expected_recipient=expected_recipient,
                    expected_ata=expected_ata_str,
                    actual_destination=actual_destination,
                )
                return {
                    "valid": False,
                    "error": f"Wrong recipient: {actual_destination}",
                }

            logger.info("x402.verify_onchain.validate: recipient_ok")

            # 3. Verify amount
            actual_amount = int(info["tokenAmount"]["amount"])
            if actual_amount != expected_amount:
                logger.error("x402.verify_onchain.validate: amount_mismatch")
                debug_ctx(
                    "x402.verify_onchain.validate.ctx",
                    expected_amount=expected_amount,
                    actual_amount=actual_amount,
                )
                return {
                    "valid": False,
                    "error": f"Amount mismatch: {actual_amount} != {expected_amount}",
                }

            logger.info("x402.verify_onchain.validate: amount_ok")

            # All checks passed!
            logger.info("x402.verify_onchain.validate: ok")
            return {
                "valid": True,
                "isValid": True,  # Match facilitator format
                "amount": str(actual_amount),
                "signature": signature,
                "confirmed": True,
            }

        except Exception as e:
            logger.error(
                f"x402.verify_onchain.exception: type={type(e).__name__} error={str(e)[:200]}"
            )
            return {"valid": False, "error": str(e)}

    def create_payment_required_response(
        self, amount_in_dollars: str, pay_to: str = None
    ) -> dict:
        """Create 402 Payment Required response with amount in smallest unit (micro-USDC)

        The facilitator expects the amount as an integer in the token's smallest unit.
        For USDC with 6 decimals: 0.01 USDC = 10000 micro-USDC

        Args:
            amount_in_dollars: Amount in dollars (e.g., "0.01")
            pay_to: Payment recipient wallet address (if None, uses self.pay_to_address)
        """
        # Convert dollar string to smallest unit (micro-USDC, 6 decimals)
        amount_float = float(amount_in_dollars)
        amount_smallest_unit = int(amount_float * 1_000_000)

        # Use provided pay_to or fall back to self.pay_to_address
        recipient = pay_to if pay_to else self.pay_to_address

        return {
            "accepts": [
                {
                    "network": os.getenv("X402_NETWORK", "solana"),
                    "asset": os.getenv(
                        "USDC_MINT", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
                    ),
                    "payTo": recipient,
                    # Send as string of integer value in smallest units
                    "amount": str(amount_smallest_unit),
                    "description": "x402 chat donation",
                }
            ]
        }


# Configure logging
ENABLE_DEBUG_LOGGING = os.getenv("ENABLE_DEBUG_LOGGING", "false").lower() == "true"
LOG_FILE = os.getenv("LOG_FILE", "")  # Empty = no file logging

logger = logging.getLogger("superchat")
if not logger.handlers:
    log_level = logging.DEBUG if ENABLE_DEBUG_LOGGING else logging.INFO
    log_format = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler (always enabled)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(log_format)
    logger.addHandler(console_handler)
    logger.setLevel(log_level)

    # File handler (optional, for persistent logs)
    if LOG_FILE:
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=10 * 1024 * 1024,  # 10MB per file
            backupCount=5,  # Keep 5 backup files
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(log_format)
        logger.addHandler(file_handler)
        print(f"📝 Logging to file: {LOG_FILE}")

# Silence httpx logging to prevent API key leakage in URLs
# httpx logs all HTTP requests at INFO level by default
logging.getLogger("httpx").setLevel(logging.WARNING)


# ============================================================================
# HELIUS API CLIENT (DRY)
# ============================================================================


class HeliusClient:
    """
    Unified Helius API client with security best practices.

    DRY principle: All Helius API calls go through this client to:
    - Centralize API key validation
    - Standardize timeout configuration
    - Unify error handling
    - Prevent API key leakage
    """

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("helius_api_key is required")
        self.api_key = api_key
        self.rpc_base = "https://mainnet.helius-rpc.com"
        self.api_base = "https://api.helius.xyz/v0"
        self.timeout = 30.0

    async def _request(
        self, method: str, url: str, **kwargs
    ) -> httpx.Response:
        """
        Internal method to make HTTP requests with consistent configuration.

        Args:
            method: HTTP method (GET, POST)
            url: Full URL to request
            **kwargs: Additional arguments for httpx request

        Returns:
            httpx.Response object

        Raises:
            HTTPException: If request fails
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.request(method, url, **kwargs)
                return response
            except httpx.TimeoutException:
                logger.error(f"helius.timeout: url={url}")
                raise HTTPException(
                    status_code=504,
                    detail="helius api request timed out"
                )
            except httpx.RequestError as e:
                logger.error(f"helius.request_error: error={str(e)[:200]}")
                raise HTTPException(
                    status_code=502,
                    detail="helius api request failed"
                )

    async def rpc_call(self, body: dict) -> dict:
        """
        Make a JSON-RPC call to Helius RPC endpoint.

        Args:
            body: JSON-RPC request object

        Returns:
            JSON-RPC response
        """
        url = f"{self.rpc_base}/?api-key={self.api_key}"
        response = await self._request(
            "POST",
            url,
            json=body,
            headers={"Content-Type": "application/json"}
        )
        return Response(
            content=response.text,
            media_type="application/json",
            status_code=response.status_code
        )

    async def get_transactions(
        self, wallet_address: str, limit: int = 100
    ) -> list:
        """
        Get enhanced transactions for a wallet address.

        Args:
            wallet_address: Solana wallet address
            limit: Maximum number of transactions to return

        Returns:
            List of enhanced transaction objects

        Raises:
            HTTPException: If request fails
        """
        url = f"{self.api_base}/addresses/{wallet_address}/transactions"
        response = await self._request(
            "GET",
            url,
            params={"api-key": self.api_key, "limit": limit}
        )

        if not response.is_success:
            logger.error(f"helius.transactions.error: status={response.status_code}")
            raise HTTPException(
                status_code=response.status_code,
                detail=f"helius api request failed: {response.text[:200]}"
            )

        return response.json()

    async def get_transactions_by_signatures(
        self, signatures: list[str]
    ) -> list:
        """
        Get enhanced transactions by transaction signatures.

        Args:
            signatures: List of transaction signatures

        Returns:
            List of enhanced transaction objects

        Raises:
            HTTPException: If request fails
        """
        url = f"{self.api_base}/transactions"
        response = await self._request(
            "POST",
            url,
            params={"api-key": self.api_key},
            json={"transactions": signatures},
            headers={"Content-Type": "application/json"}
        )

        if not response.is_success:
            logger.error(f"helius.transactions_by_sig.error: status={response.status_code}")
            raise HTTPException(
                status_code=response.status_code,
                detail=f"helius api request failed: {response.text[:200]}"
            )

        return response.json()

    async def get_balances(self, wallet_address: str) -> dict:
        """
        Get token balances for a wallet address.

        Args:
            wallet_address: Solana wallet address

        Returns:
            Token balances object

        Raises:
            HTTPException: If request fails
        """
        url = f"{self.api_base}/addresses/{wallet_address}/balances"
        response = await self._request(
            "GET",
            url,
            params={"api-key": self.api_key}
        )

        if not response.is_success:
            logger.error(f"helius.balances.error: status={response.status_code}")
            raise HTTPException(
                status_code=response.status_code,
                detail=f"helius api request failed: {response.text[:200]}"
            )

        return response.json()


# Configuration constants
DEFAULT_DONATION_AMOUNT = os.getenv("DEFAULT_DONATION_AMOUNT", "1.00").replace("$", "")
MAX_SENDER_NAME_LENGTH = int(os.getenv("MAX_SENDER_NAME_LENGTH", "12"))
MAX_MESSAGE_LENGTH = int(os.getenv("MAX_MESSAGE_LENGTH", "200"))
X402_NETWORK = os.getenv("X402_NETWORK", "solana")
X402_MAX_AMOUNT = os.getenv("X402_MAX_AMOUNT", "10000")
X402_TIMEOUT = os.getenv("X402_TIMEOUT", "60")
USDC_MINT = os.getenv("USDC_MINT", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")
FACILITATOR_URL = os.getenv("FACILITATOR_URL", "https://facilitator.x402.rs")
PAY_TO_ADDRESS = os.getenv("PAY_TO_ADDRESS")
PORT = int(os.getenv("PORT", "8765"))


def debug_ctx(context: str, **fields):
    """
    Debug-only structured log with sensitive values.
    context: short tag like "x402.verify_onchain.request"
    fields: dict of relevant internal values (wallets, sigs, payloads, etc.)
    Only prints if ENABLE_DEBUG_LOGGING=true.
    """
    if not ENABLE_DEBUG_LOGGING:
        return
    if fields:
        logger.debug(f"{context} {fields}")
    else:
        logger.debug(context)


# ============================================================================
# DATABASE MODELS
# ============================================================================

Base = declarative_base()


class ReceiverId(Base):
    __tablename__ = "receiver_ids"

    public_key = Column(String, primary_key=True)  # Account wallet (logged in as)
    id = Column(String, nullable=False)
    pay_to_address = Column(
        String, nullable=True
    )  # Where donations are sent (can be different from account)
    username = Column(String, nullable=True, unique=True)  # URL-friendly username

    created_at = Column(DateTime, default=datetime.utcnow)

    # Donation Settings (per-user configuration)
    default_donation_amount = Column(String, default="0.01", nullable=False)  # Default amount in USDC

    # TTS Settings (per-user configuration)
    tts_enabled = Column(Boolean, default=True, nullable=False)
    tts_voice_index = Column(Integer, default=0, nullable=False)
    tts_rate = Column(Float, default=1.0, nullable=False)
    tts_pitch = Column(Float, default=1.0, nullable=False)
    tts_volume = Column(Float, default=1.0, nullable=False)

    def to_dict(self):
        return {
            "public_key": self.public_key,
            "id": self.id,
            "pay_to_address": self.pay_to_address,
            "username": self.username,
            "created_at": self.created_at,
            "tts_settings": {
                "enabled": self.tts_enabled,
                "voice_index": self.tts_voice_index,
                "rate": self.tts_rate,
                "pitch": self.tts_pitch,
                "volume": self.tts_volume,
            },
        }

    def get_payment_address(self) -> str:
        """Get payment address - raises error if not configured."""
        if not self.pay_to_address:
            raise ValueError(
                "Payment address not configured. User must set up pay_to_address in settings before accepting donations."
            )
        return self.pay_to_address


class AuthSession(Base):
    __tablename__ = "auth_session"

    id = Column(String, primary_key=True)
    public_key = Column(String, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "created_at": self.created_at,
        }


class Donation(Base):
    """Donation record with moderation support."""

    __tablename__ = "donations"

    # Primary key - use auto-increment for x402 donations
    id = Column(Integer, primary_key=True, autoincrement=True)

    # x402 donation fields
    sender_name = Column(String(12), nullable=False, default="anon")  # Max 12 chars
    message = Column(
        EncryptedString(240), nullable=False, default=""
    )  # Encrypted at rest
    amount = Column(Float, nullable=False)
    token_symbol = Column(String, nullable=False, default="USDC")

    # Multi-user support: which receiver this donation is for
    receiver_id = Column(String, nullable=True)  # NULL for legacy donations

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    # Moderation fields
    status = Column(String, default="pending")  # pending, approved, rejected
    moderated_at = Column(DateTime, nullable=True)

    # Payment source tracking
    source = Column(String, default="x402")  # "blockchain" or "x402"

    def to_dict(self):
        return {
            "id": self.id,
            "sender_name": self.sender_name,
            "message": self.message,  # Auto-decrypted by TypeDecorator
            "amount": self.amount,
            "token_symbol": self.token_symbol,
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
# DATABASE HELPER FUNCTIONS (DRY)
# ============================================================================


def get_receiver_or_404(db: Session, receiver_id: str) -> ReceiverId:
    """Get receiver by ID or raise 404.

    DRY helper - used 8+ times throughout the codebase.
    """
    receiver = db.query(ReceiverId).filter(ReceiverId.id == receiver_id).first()
    if not receiver:
        raise HTTPException(status_code=404, detail="Receiver not found")
    return receiver


def get_receiver_by_username_or_id(db: Session, identifier: str) -> ReceiverId:
    """Get receiver by username or ID.

    Tries username first, then falls back to receiver_id for backward compatibility.
    """
    # Try username first
    receiver = db.query(ReceiverId).filter(ReceiverId.username == identifier).first()
    if receiver:
        return receiver

    # Fallback to id
    receiver = db.query(ReceiverId).filter(ReceiverId.id == identifier).first()
    if not receiver:
        raise HTTPException(status_code=404, detail="Receiver not found")

    return receiver


def get_donation_or_404(db: Session, donation_id: int) -> Donation:
    """Get donation by ID or raise 404.

    DRY helper - used 4 times in moderation endpoints.
    """
    donation = db.query(Donation).filter(Donation.id == donation_id).first()
    if not donation:
        raise HTTPException(status_code=404, detail="Donation not found")
    return donation


def verify_donation_ownership(donation: Donation, receiver_id: str) -> None:
    """Verify user owns this donation or raise 403.

    DRY helper - authorization check used 4 times in moderation endpoints.
    Rejects NULL receiver_id for security (prevents authorization bypass).
    """
    if not donation.receiver_id or donation.receiver_id != receiver_id:
        raise HTTPException(
            status_code=403, detail="Not authorized to moderate this donation"
        )


# ============================================================================
# CLI DONATION FETCHER
# ============================================================================

# Constants
# AI16Z_MINT = "HeLp6NuQkmYB4pYWo2zYs22mESHXPQYzXbB8n4V98jwC"  # Future: multi-token X402 support
HELIUS_BASE = "https://api.helius.xyz/v0"
RPC_BASE = "https://mainnet.helius-rpc.com"
# MEMO_PID = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"  # Legacy: memo parsing


# ============================================================================
# FASTAPI APPLICATION
# ============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    # Startup
    init_db()
    monitor_task = asyncio.create_task(monitor_new_donations())
    logger.info("server.startup: complete")

    yield

    # Shutdown - graceful cleanup
    logger.info("server.shutdown: begin")

    # Cancel background monitor task
    monitor_task.cancel()
    try:
        await asyncio.wait_for(monitor_task, timeout=5.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    logger.info("server.shutdown: background_task_stopped")

    # Close overlay WebSocket connections gracefully
    for ws in overlay_connections[:]:
        try:
            await ws.close(code=1001, reason="Server shutting down")
        except Exception:
            pass
    overlay_connections.clear()

    # Close dashboard WebSocket connections gracefully
    for receiver_id, connections in list(dashboard_connections.items()):
        for ws in connections[:]:
            try:
                await ws.close(code=1001, reason="Server shutting down")
            except Exception:
                pass
    dashboard_connections.clear()

    logger.info("server.shutdown: complete")


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

# Initialize Solana x402 (pay_to_address set per-request based on receiver)
# Using constant from configuration section above
facilitator_url = FACILITATOR_URL

# Initialize Helius client (DRY - single instance)
helius_client = HeliusClient(api_key=HELIUS_API_KEY) if HELIUS_API_KEY else None

# Initialize wallet privacy scorer
privacy_scorer = WalletPrivacyScorer(helius_api_key=HELIUS_API_KEY)

# WebSocket connections
# Overlay remains public (for OBS)
overlay_connections: List[WebSocket] = []

# Dashboard connections by receiver_id for multi-user support
# Format: {receiver_id: [websocket1, websocket2, ...]}
dashboard_connections: Dict[str, List[WebSocket]] = {}


# WebSocket authentication helper
async def verify_websocket_auth(websocket: WebSocket, db: Session) -> str:
    """
    Verify WebSocket connection is authenticated.
    Returns receiver_id if valid, closes connection and raises HTTPException otherwise.
    """
    cookies = websocket.cookies
    session_id = cookies.get("session_id")

    if not session_id:
        await websocket.close(code=1008, reason="Authentication required")
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Verify session exists and is valid
    session = db.get(AuthSession, session_id)
    if not session:
        await websocket.close(code=1008, reason="Session not found")
        raise HTTPException(status_code=401, detail="Invalid session")

    # Check session age (1 hour expiry for WebSocket connections)
    # This prevents session fixation attacks if wallet is transferred
    session_age = datetime.utcnow() - session.created_at
    if session_age > timedelta(hours=1):
        await websocket.close(code=1008, reason="Session expired")
        raise HTTPException(status_code=401, detail="Session expired")

    # Get receiver from public key
    receiver = db.get(ReceiverId, session.public_key)
    if not receiver:
        await websocket.close(code=1008, reason="Invalid session")
        raise HTTPException(status_code=401, detail="Receiver not found")

    return receiver.id


# Request models
class ModerationRequest(BaseModel):
    donation_id: str


class DonationRequest(BaseModel):
    sender_name: str = "anon"
    message: str = ""
    amount: float = float(DEFAULT_DONATION_AMOUNT)
    receiver_id: str  # NEW: Required for multi-user support

    class Config:
        json_schema_extra = {
            "example": {
                "sender_name": "anon",
                "message": "",
                "amount": 10.0,
                "receiver_id": "abc123",
            }
        }


class TTSSettingsRequest(BaseModel):
    enabled: bool = True
    voice_index: int = 0
    rate: float = 1.0
    pitch: float = 1.0
    volume: float = 1.0

    class Config:
        json_schema_extra = {
            "example": {
                "enabled": True,
                "voice_index": 0,
                "rate": 1.0,
                "pitch": 1.0,
                "volume": 1.0,
            }
        }


# In-memory playing state (fast, ephemeral)
currently_playing = None  # {signature: str, donation_data: dict}

# Replay attack prevention: Track recently used transaction signatures
# In-memory only (not persisted) for privacy - expires after 24 hours
# Key: signature, Value: timestamp when used
used_signatures: dict[str, float] = {}
SIGNATURE_EXPIRY_HOURS = 24


def get_current_user(request: Request, db: Session):
    session_id = request.cookies.get("session_id")

    # Check if session_id cookie exists
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    found = db.get(AuthSession, session_id)
    if found is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if datetime.utcnow() - found.created_at > timedelta(days=7):
        db.delete(found)
        db.commit()
        raise HTTPException(status_code=401, detail="Session expired")

    receiver = db.get(ReceiverId, found.public_key)
    if receiver is None:
        db.delete(found)
        db.commit()
        raise HTTPException(status_code=500, detail="Id not found")

    return receiver


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.get("/index.css")
async def root():
    return FileResponse("static/index.css")


@app.get("/index.js")
async def root():
    return FileResponse("static/index.js")


@app.get("/overlay")
async def root():
    return FileResponse("static/overlay.html")


@app.get("/global.css")
async def dashboard():
    return FileResponse("static/global.css")


@app.get("/dashboard")
async def dashboard():
    """
    Serve dashboard HTML.
    Auth is now handled client-side via wallet signatures (no cookies needed).
    """
    return FileResponse("static/dashboard.html")


@app.get("/dashboard.css")
async def dashboard():
    return FileResponse("static/dashboard.css")


@app.get("/dashboard.js")
async def dashboard():
    return FileResponse("static/dashboard.js")


@app.get("/donate/{identifier}")
async def serve_donate_page(identifier: str, db: Session = Depends(get_db)):
    # Validate receiver exists (supports both username and id)
    receiver = get_receiver_by_username_or_id(db, identifier)

    # Redirect to username URL if user has username and we're on receiver_id URL
    # This ensures consistent URLs and better UX
    from fastapi.responses import RedirectResponse
    if receiver.username and identifier == receiver.id:
        return RedirectResponse(url=f"/donate/{receiver.username}", status_code=301)

    # Read HTML and inject identifier to prevent flash
    with open("static/donate.html", "r") as f:
        html = f.read()

    # Replace the default title with the identifier
    html = html.replace("<h1 id=\"pageTitle\">x402 Chat</h1>", f"<h1 id=\"pageTitle\">@{identifier}</h1>")

    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html)


@app.get("/api/receiver/{identifier}")
async def get_receiver_info(identifier: str, db: Session = Depends(get_db)):
    """Get public receiver information (no authentication required)."""
    receiver = get_receiver_by_username_or_id(db, identifier)

    return {
        "id": receiver.id,
        "username": receiver.username,
        "default_donation_amount": receiver.default_donation_amount,
    }


@app.get("/donate.css")
async def donate():
    return FileResponse("static/donate.css")


@app.get("/donate.js")
async def donate():
    return FileResponse("static/donate.js")


@app.get("/privacy-scorer.js")
async def serve_privacy_scorer_js():
    return FileResponse("static/privacy-scorer.js", media_type="application/javascript")


@app.get("/wallet-auth.js")
async def wallet_auth():
    return FileResponse("static/wallet-auth.js", media_type="application/javascript")


@app.get("/favicon.svg")
async def favicon():
    return FileResponse("static/favicon.svg", media_type="image/svg+xml")


@app.get("/x402chat.png")
async def logo():
    return FileResponse("static/x402chat.png", media_type="image/png")


@app.get("/health")
async def health():
    """Health check with dependency verification."""
    checks = {"status": "ok", "checks": {}}

    # Database connectivity check
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        checks["checks"]["database"] = "ok"
    except Exception as e:
        checks["status"] = "degraded"
        checks["checks"]["database"] = f"error: {type(e).__name__}"
        logger.error(f"health.database_check: failed error={e}")
    finally:
        db.close()

    # Helius API configuration check
    if helius_client:
        checks["checks"]["helius"] = "configured"
    else:
        checks["checks"]["helius"] = "not configured"

    # Encryption key check
    try:
        # Test encryption round-trip
        test_msg = "health_check"
        encrypted = FERNET_CIPHER.encrypt(test_msg.encode())
        decrypted = FERNET_CIPHER.decrypt(encrypted).decode()
        checks["checks"]["encryption"] = "ok" if decrypted == test_msg else "mismatch"
    except Exception as e:
        checks["status"] = "degraded"
        checks["checks"]["encryption"] = f"error: {type(e).__name__}"

    return checks


class AuthChallengeRequest(BaseModel):
    publicKey: str


challenges = {}

# Load whitelist from file
whitelist = []
WHITELIST_FILE = "whitelist.txt"


def load_whitelist():
    """Load wallet addresses from whitelist file."""
    global whitelist
    try:
        if os.path.exists(WHITELIST_FILE):
            with open(WHITELIST_FILE, "r") as f:
                # Read lines, strip whitespace, and filter out empty lines and comments
                whitelist = [
                    line.strip()
                    for line in f
                    if line.strip() and not line.strip().startswith("#")
                ]
            logger.info(f"✅ Loaded {len(whitelist)} addresses from {WHITELIST_FILE}")
        else:
            logger.warning(f"⚠️  Whitelist file not found: {WHITELIST_FILE}")
            whitelist = []
    except Exception as e:
        logger.error(f"❌ Error loading whitelist: {e}")
        whitelist = []


# Load whitelist on startup
load_whitelist()


@app.post("/api/auth/challenge")
async def auth_challenge(req: AuthChallengeRequest):
    # Note: Whitelist check disabled for beta - anyone can authenticate
    # Whitelist is still loaded and can be checked via API or file inspection
    # found = False
    # for w in whitelist:
    #     if w == req.publicKey:
    #         found = True
    #         break
    # if not found:
    #     raise HTTPException(status_code=401, detail="Not whitelisted")

    nonce = secrets.token_hex(16)
    timestamp = int(time.time())
    message = f"Sign this message to authenticate with x402 Chat.\nNonce: {nonce}\nIssued: {timestamp}"
    challenges[req.publicKey] = {"message": message, "timestamp": timestamp}
    return {"message": message}


class AuthVerifyRequest(BaseModel):
    message: str
    publicKey: str
    signature: str


class WalletAuth(BaseModel):
    """Wallet-based authentication for protected endpoints"""

    publicKey: str
    message: str
    signature: str
    timestamp: int


def verify_wallet_auth(
    auth: WalletAuth, db: Session, max_age_seconds: int = 300
) -> tuple[str, bool]:
    """
    Verify wallet-based authentication and return the receiver_id and needs_config flag.

    Args:
        auth: WalletAuth object with publicKey, message, signature, timestamp
        db: Database session
        max_age_seconds: Maximum age of the message in seconds (default 5 minutes)

    Returns:
        tuple: (receiver_id, needs_config) where needs_config is True if pay_to_address is not set

    Raises:
        HTTPException: If auth is invalid
    """
    # 1. Check timestamp is recent (prevent replay attacks)
    now = int(time.time())
    if abs(now - auth.timestamp) > max_age_seconds:
        raise HTTPException(
            status_code=401,
            detail=f"Message too old or from future (age: {abs(now - auth.timestamp)}s, max: {max_age_seconds}s)",
        )

    # 2. Verify message format includes timestamp
    if str(auth.timestamp) not in auth.message:
        raise HTTPException(status_code=401, detail="Message must include timestamp")

    # 3. Verify signature
    try:
        # Decode public key
        public_key_bytes = base58.b58decode(auth.publicKey)
        verify_key = nacl.signing.VerifyKey(public_key_bytes)

        # Decode signature
        signature_bytes = base58.b58decode(auth.signature)

        # Verify signature matches message
        message_bytes = auth.message.encode("utf-8")
        verify_key.verify(message_bytes, signature_bytes)

    except nacl.exceptions.BadSignatureError:
        raise HTTPException(status_code=401, detail="Invalid signature")
    except Exception as e:
        raise HTTPException(
            status_code=401, detail=f"Signature verification failed: {str(e)}"
        )

    # 4. Check if this wallet has a receiver_id, create if not exists
    receiver = db.get(ReceiverId, auth.publicKey)
    is_new = False
    if receiver is None:
        # Auto-register wallet on first sign-in
        import secrets

        receiver_id = secrets.token_urlsafe(8)
        receiver = ReceiverId(public_key=auth.publicKey, id=receiver_id)
        db.add(receiver)
        db.commit()
        is_new = True
        logger.info(f"auth.wallet.register: receiver_id={receiver_id} new_user=true")
        debug_ctx("auth.wallet.register.ctx", public_key=auth.publicKey)

    # Check if user needs to configure payment address
    needs_config = receiver.pay_to_address is None or receiver.pay_to_address == ""

    return receiver.id, needs_config


@app.post("/api/auth/verify")
async def auth_verify(req: AuthVerifyRequest, db: Session = Depends(get_db)):
    record = challenges.get(req.publicKey)

    if not record or record["message"] != req.message:
        raise HTTPException(status_code=400, detail="Invalid or expired challenge")

    try:
        public_key_bytes = base58.b58decode(req.publicKey)
        signature_bytes = base58.b58decode(req.signature)
        message_bytes = req.message.encode("utf-8")

        verify_key = nacl.signing.VerifyKey(public_key_bytes)
        verify_key.verify(message_bytes, signature_bytes)

        challenges.pop(req.publicKey, None)

        receiver = db.get(ReceiverId, req.publicKey)

        prev_sessions = (
            db.query(AuthSession).filter(AuthSession.public_key == req.publicKey).all()
        )

        for s in prev_sessions:
            db.delete(s)

        session_id = secrets.token_urlsafe(16)
        session = AuthSession(id=session_id, public_key=req.publicKey)
        db.add(session)

        rid = None

        if receiver is None:
            rid = secrets.token_urlsafe(10)
            item = ReceiverId(public_key=req.publicKey, id=rid)
            db.add(item)
        else:
            rid = receiver.id

        db.commit()

        content = json.dumps({"id": rid})
        res = Response(content=content, media_type="application/json")
        res.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,  # JS cannot read it (prevents XSS stealing)
            secure=True,  # only send over HTTPS
            samesite="Lax",  # protects CSRF
            max_age=3600,
        )

        return res

    except nacl.exceptions.BadSignatureError:
        raise HTTPException(status_code=401, detail="Invalid signature")


@app.post("/api/auth/wallet-verify")
async def wallet_verify(auth: WalletAuth, db: Session = Depends(get_db)):
    """
    Verify wallet-based authentication.
    Returns the receiver_id and needs_config flag if authentication succeeds.

    Also creates session cookie for compatibility with dashboard endpoints.
    """
    receiver_id, needs_config = verify_wallet_auth(auth, db)

    # Create session cookie for dashboard compatibility
    session_id = secrets.token_urlsafe(16)
    session = AuthSession(id=session_id, public_key=auth.publicKey)
    db.add(session)
    db.commit()

    content = json.dumps({
        "id": receiver_id,
        "publicKey": auth.publicKey,
        "needsConfig": needs_config
    })
    res = Response(content=content, media_type="application/json")
    res.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        secure=True,
        samesite="Lax",
        max_age=3600,
    )

    return res


@app.get("/api/auth/id")
async def auth_id(request: Request, db: Session = Depends(get_db)):
    receiver = get_current_user(request, db)
    return {"id": receiver.id}


@app.get("/api/auth/clear")
async def auth_clear(request: Request, db: Session = Depends(get_db)):
    session_id = request.cookies.get("session_id")
    found = db.get(AuthSession, session_id)

    if found is None:
        return {"ok": True}

    db.delete(found)
    db.commit()

    # session_id = request.cookies.delete("session_id")


@app.get("/api/config")
async def get_config(request: Request, db: Session = Depends(get_db)):
    """Get current configuration and statistics."""
    # Verify authentication
    receiver = get_current_user(request, db)

    # Get donation statistics (filtered by receiver_id)
    total_donations = (
        db.query(Donation).filter(Donation.receiver_id == receiver.id).count()
    )
    pending_count = (
        db.query(Donation)
        .filter(Donation.status == "pending", Donation.receiver_id == receiver.id)
        .count()
    )
    approved_count = (
        db.query(Donation)
        .filter(Donation.status == "approved", Donation.receiver_id == receiver.id)
        .count()
    )
    rejected_count = (
        db.query(Donation)
        .filter(Donation.status == "rejected", Donation.receiver_id == receiver.id)
        .count()
    )

    # Get total amounts (filtered by receiver_id)
    total_amount = (
        db.query(Donation)
        .filter(Donation.receiver_id == receiver.id)
        .with_entities(func.sum(Donation.amount))
        .scalar()
        or 0
    )

    # Generate overlay URL with user's TTS settings
    tts_params = []
    if not receiver.tts_enabled:
        tts_params.append("tts=false")
    if receiver.tts_voice_index != 0:
        tts_params.append(f"voice={receiver.tts_voice_index}")
    if receiver.tts_rate != 1.0:
        tts_params.append(f"rate={receiver.tts_rate}")
    if receiver.tts_pitch != 1.0:
        tts_params.append(f"pitch={receiver.tts_pitch}")
    if receiver.tts_volume != 1.0:
        tts_params.append(f"volume={receiver.tts_volume}")

    overlay_url = f"{request.base_url}overlay"
    if tts_params:
        overlay_url += "?" + "&".join(tts_params)

    return {
        "x402_settings": {
            "network": X402_NETWORK,
            "facilitator_url": FACILITATOR_URL,
            "pay_to_address": receiver.pay_to_address,  # Where donations are sent (None if not configured)
            "usdc_mint": USDC_MINT,
            "max_amount": X402_MAX_AMOUNT,
            "timeout": X402_TIMEOUT,
            "default_donation_amount": receiver.default_donation_amount,  # Per-user default
        },
        "content_limits": {
            "max_sender_name_length": MAX_SENDER_NAME_LENGTH,
            "max_message_length": MAX_MESSAGE_LENGTH,
        },
        "server": {
            "port": PORT,
            "database_url": DATABASE_URL.replace("sqlite:///", ""),
        },
        "statistics": {
            "total_donations": total_donations,
            "pending": pending_count,
            "approved": approved_count,
            "rejected": rejected_count,
            "total_amount": float(total_amount),
        },
        "tts_settings": {
            "enabled": receiver.tts_enabled,
            "voice_index": receiver.tts_voice_index,
            "rate": receiver.tts_rate,
            "pitch": receiver.tts_pitch,
            "volume": receiver.tts_volume,
        },
        "user": {
            "receiver_id": receiver.id,
            "username": receiver.username,
            "donation_url": f"{request.base_url}donate/{receiver.username if receiver.username else receiver.id}",
            "overlay_url": overlay_url,
            "account": receiver.public_key,  # Account wallet (logged in as)
        },
    }


@app.post("/api/config/tts")
async def update_tts_settings(
    tts_request: TTSSettingsRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update TTS settings for authenticated user."""
    # Verify authentication
    receiver = get_current_user(request, db)

    # Validate settings
    if tts_request.rate < 0.1 or tts_request.rate > 10:
        raise HTTPException(status_code=400, detail="Rate must be between 0.1 and 10")

    if tts_request.pitch < 0 or tts_request.pitch > 2:
        raise HTTPException(status_code=400, detail="Pitch must be between 0 and 2")

    if tts_request.volume < 0 or tts_request.volume > 1:
        raise HTTPException(status_code=400, detail="Volume must be between 0 and 1")

    if tts_request.voice_index < 0:
        raise HTTPException(status_code=400, detail="Voice index must be non-negative")

    # Update TTS settings
    receiver.tts_enabled = tts_request.enabled
    receiver.tts_voice_index = tts_request.voice_index
    receiver.tts_rate = tts_request.rate
    receiver.tts_pitch = tts_request.pitch
    receiver.tts_volume = tts_request.volume

    db.commit()

    logger.info(f"✅ Updated TTS settings for user {receiver.id}")

    return {
        "status": "success",
        "message": "TTS settings updated",
        "tts_settings": {
            "enabled": receiver.tts_enabled,
            "voice_index": receiver.tts_voice_index,
            "rate": receiver.tts_rate,
            "pitch": receiver.tts_pitch,
            "volume": receiver.tts_volume,
        },
    }


@app.post("/api/config/username")
async def update_username(
    request: Request,
    db: Session = Depends(get_db),
):
    """Update username for the authenticated user."""
    # Verify authentication
    receiver = get_current_user(request, db)

    # Parse request body
    body = await request.json()
    new_username = body.get("username", "").strip()

    # Validate username (alphanumeric, dash, underscore, 3-20 chars)
    import re

    if new_username:
        if not re.match(r"^[a-zA-Z0-9_-]{3,20}$", new_username):
            raise HTTPException(
                status_code=400,
                detail="Username must be 3-20 characters (letters, numbers, dash, underscore)",
            )

        # Check if username is already taken
        existing = (
            db.query(ReceiverId)
            .filter(ReceiverId.username == new_username)
            .filter(ReceiverId.public_key != receiver.public_key)
            .first()
        )

        if existing:
            raise HTTPException(status_code=400, detail="Username already taken")

    # Update username (empty string means no username)
    receiver.username = new_username if new_username else None
    db.commit()

    logger.info(
        f"config.username.update: receiver_id={receiver.id} username={new_username or 'cleared'}"
    )

    return {
        "success": True,
        "username": receiver.username,
    }


@app.post("/api/config/pay-to-address")
async def update_pay_to_address(
    request: Request,
    db: Session = Depends(get_db),
):
    """Update payment address for the authenticated user."""
    # Require authentication (returns ReceiverId object)
    receiver = get_current_user(request, db)

    # Parse request body
    body = await request.json()
    new_pay_to = body.get("pay_to_address", "").strip()

    # Require a payment address (prevent empty/null)
    if not new_pay_to:
        raise HTTPException(
            status_code=400,
            detail="Payment address is required. You must set a wallet address to receive donations."
        )

    # Validate wallet address (basic Solana address validation)
    if len(new_pay_to) < 32 or len(new_pay_to) > 44:
        raise HTTPException(status_code=400, detail="Invalid Solana wallet address")

    # Prevent self-donations: payment address cannot be the same as account wallet
    if new_pay_to == receiver.public_key:
        raise HTTPException(
            status_code=400,
            detail="Payment address cannot be the same as your account wallet. This would allow you to donate to yourself. Please use a different wallet address."
        )

    # Update payment address
    receiver.pay_to_address = new_pay_to
    db.commit()

    logger.info(
        f"config.pay_to_address.update: receiver_id={receiver.id} wallet={new_pay_to[:8]}..."
    )

    return {
        "success": True,
        "pay_to_address": receiver.pay_to_address,
    }


@app.post("/api/config/default-donation-amount")
async def update_default_donation_amount(
    request: Request,
    db: Session = Depends(get_db),
):
    """Update default donation amount for the authenticated user."""
    # Require authentication (returns ReceiverId object)
    receiver = get_current_user(request, db)

    # Parse request body
    body = await request.json()
    new_amount = body.get("default_donation_amount", "").strip()

    # Validate amount is a valid positive number
    try:
        amount_float = float(new_amount)
        if amount_float <= 0:
            raise HTTPException(
                status_code=400,
                detail="Default donation amount must be greater than 0"
            )
        if amount_float > 1000:
            raise HTTPException(
                status_code=400,
                detail="Default donation amount cannot exceed $1000"
            )
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid amount format. Please enter a valid number."
        )

    # Update default donation amount
    receiver.default_donation_amount = new_amount
    db.commit()

    logger.info(
        f"config.default_amount.update: receiver_id={receiver.id} amount={new_amount}"
    )

    return {
        "success": True,
        "default_donation_amount": receiver.default_donation_amount,
    }


@app.get("/api/events/playing")
async def get_currently_playing():
    """Get currently playing donation."""
    return {
        "playing": currently_playing["donation_id"] if currently_playing else None,
        "donation": currently_playing["donation_data"] if currently_playing else None,
    }


# Moderation API endpoints
@app.get("/api/events/pending")
async def get_pending_donations(request: Request, db: Session = Depends(get_db)):
    """Get pending donations for moderation."""
    # Require authentication
    receiver = get_current_user(request, db)

    donations = (
        db.query(Donation)
        .filter(Donation.status == "pending")
        .filter(Donation.receiver_id == receiver.id)
        .order_by(Donation.created_at.asc())
        .all()
    )

    return [d.to_dict() for d in donations]


@app.get("/api/events/approved")
async def get_approved_donations(request: Request, db: Session = Depends(get_db)):
    """Get all approved donations."""
    # Require authentication
    receiver = get_current_user(request, db)

    donations = (
        db.query(Donation)
        .filter(Donation.status == "approved")
        .filter(Donation.receiver_id == receiver.id)
        .order_by(Donation.moderated_at.desc())
        .all()
    )

    return [d.to_dict() for d in donations]


@app.get("/api/events/rejected")
async def get_rejected_donations(request: Request, db: Session = Depends(get_db)):
    """Get all rejected donations."""
    # Require authentication
    receiver = get_current_user(request, db)

    donations = (
        db.query(Donation)
        .filter(Donation.status == "rejected")
        .filter(Donation.receiver_id == receiver.id)
        .order_by(Donation.moderated_at.desc())
        .all()
    )

    return [d.to_dict() for d in donations]


@app.get("/api/export/csv")
async def export_donations_csv(request: Request, db: Session = Depends(get_db)):
    """Export all donations to CSV format."""
    # Require authentication
    receiver = get_current_user(request, db)

    donations = (
        db.query(Donation)
        .filter(Donation.receiver_id == receiver.id)
        .order_by(Donation.created_at.desc())
        .all()
    )

    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow(
        [
            "ID",
            "Created At",
            "Sender Name",
            "Amount",
            "Token Symbol",
            "Message",
            "Status",
            "Moderated At",
        ]
    )

    # Write data rows
    for donation in donations:
        writer.writerow(
            [
                donation.id,
                donation.created_at.isoformat() if donation.created_at else "",
                donation.sender_name or "",
                donation.amount,
                donation.token_symbol or "",
                donation.message or "",
                donation.status,
                donation.moderated_at.isoformat() if donation.moderated_at else "",
            ]
        )

    output.seek(0)
    response = StreamingResponse(
        io.StringIO(output.getvalue()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=donations.csv"},
    )
    return response


@app.post("/api/events/play")
async def play_donation(
    moderation_request: ModerationRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Start playing a donation (in-memory state)."""
    # Require authentication
    receiver = get_current_user(request, db)

    global currently_playing

    # Find donation and verify ownership
    donation = get_donation_or_404(db, int(moderation_request.donation_id))
    verify_donation_ownership(donation, receiver.id)

    if donation.status != "pending":
        raise HTTPException(status_code=400, detail="Donation is not pending")

    # Hide any currently playing donation
    if currently_playing:
        await broadcast_hide_donation(currently_playing["donation_id"])

    # Set as currently playing (in-memory only) - use id
    identifier = str(donation.id)
    currently_playing = {"donation_id": identifier, "donation_data": donation.to_dict()}

    # Broadcast to overlay
    await broadcast_approved_donation(donation.to_dict())

    return {"status": "playing"}


@app.post("/api/events/approve")
async def approve_donation(
    moderation_request: ModerationRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Approve a playing donation (database update)."""
    # Require authentication
    receiver = get_current_user(request, db)

    global currently_playing

    # Find donation and verify ownership FIRST (before checking playing state to prevent TOCTOU)
    donation = get_donation_or_404(db, int(moderation_request.donation_id))
    verify_donation_ownership(donation, receiver.id)

    # Check if this donation is currently playing (after authorization check)
    if (
        not currently_playing
        or currently_playing["donation_id"] != moderation_request.donation_id
    ):
        raise HTTPException(status_code=400, detail="Donation is not currently playing")

    # Update database: pending → approved
    donation.status = "approved"
    donation.moderated_at = datetime.utcnow()
    db.commit()

    # Hide from overlay - use id (signature no longer stored)
    identifier = str(donation.id)
    await broadcast_hide_donation(identifier)

    # Clear playing state
    currently_playing = None

    return {"status": "approved"}


@app.post("/api/events/reject")
async def reject_donation(
    moderation_request: ModerationRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Reject a donation."""
    # Require authentication
    receiver = get_current_user(request, db)

    global currently_playing

    # Find donation and verify ownership
    donation = get_donation_or_404(db, int(moderation_request.donation_id))
    verify_donation_ownership(donation, receiver.id)

    # If this donation is currently playing, stop it
    if currently_playing and currently_playing["donation_id"] == moderation_request.donation_id:
        # Hide from overlay
        await broadcast_hide_donation(moderation_request.donation_id)
        # Clear playing state
        currently_playing = None

    donation.status = "rejected"
    donation.moderated_at = datetime.utcnow()
    db.commit()

    return {"status": "rejected"}


@app.post("/api/events/restore")
async def restore_donation(
    moderation_request: ModerationRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Restore a donation back to pending status."""
    # Require authentication
    receiver = get_current_user(request, db)

    # Find donation and verify ownership
    donation = get_donation_or_404(db, int(moderation_request.donation_id))
    verify_donation_ownership(donation, receiver.id)

    # Restore to pending status
    donation.status = "pending"
    donation.moderated_at = None
    db.commit()

    # Broadcast to dashboard so it appears in pending tab (only to owner's dashboards)
    if donation.receiver_id:
        await broadcast_new_donation(donation.to_dict(), donation.receiver_id)

    return {"status": "restored"}


# x402 Donation API
@app.post("/api/donate/{identifier}")
async def submit_donation(
    identifier: str,
    donation_request: DonationRequest,
    db: Session = Depends(get_db),
    payment_header: str = Header(None, alias="x-402-payment"),
):
    """Submit donation via x402 payment - private message storage.

    Args:
        identifier: Either username or receiver_id (tries username first)
    """

    # Validate identifier exists and get payment address (supports username or receiver_id)
    receiver = get_receiver_by_username_or_id(db, identifier)

    # Check if payment address is configured
    try:
        expected_recipient = receiver.get_payment_address()
    except ValueError as e:
        logger.error(
            f"donation.submit: payment_address_not_configured identifier={identifier} receiver_id={receiver.id}"
        )
        raise HTTPException(
            status_code=400,
            detail="This creator has not configured their payment address yet. Please ask them to set up their payment address in dashboard settings before accepting donations."
        )

    logger.info(
        f"donation.submit: receiver_found identifier={identifier} receiver_id={receiver.id} wallet={expected_recipient[:8]}..."
    )

    # Create x402 instance with receiver's payment address
    solana_x402 = SolanaX402(
        pay_to_address=expected_recipient,
        facilitator_url=facilitator_url,
    )

    # Check for payment header
    if not payment_header:
        # Use requested amount or default
        amount = (
            str(donation_request.amount)
            if donation_request.amount
            else DEFAULT_DONATION_AMOUNT
        )
        payment_required_response = solana_x402.create_payment_required_response(amount)
        raise HTTPException(status_code=402, detail=payment_required_response)

    # Parse payment header to extract transaction data
    payment_data = None
    transaction_signature = None
    sender_address = None
    transaction_timestamp = None

    try:
        payment_data = json.loads(payment_header)
        logger.info(
            f"x402.submit: payment_header_parsed keys={list(payment_data.keys())}"
        )
        debug_ctx("x402.submit.header.ctx", payment_data=payment_data)

        # Extract transaction signature from new format
        if (
            "paymentPayload" in payment_data
            and "payload" in payment_data["paymentPayload"]
        ):
            payload = payment_data["paymentPayload"]["payload"]
            scheme = payment_data.get("paymentPayload", {}).get("scheme")

            # NEW: Extract signature for on-chain verification
            if "signature" in payload:
                transaction_signature = payload["signature"]
                logger.info("x402.submit: signature_received")
                debug_ctx(
                    "x402.submit.signature.ctx",
                    signature=transaction_signature,
                    scheme=scheme,
                    network=payment_data.get("paymentPayload", {}).get("network"),
                )

                # Log payment requirements
                if "paymentRequirements" in payment_data:
                    reqs = payment_data["paymentRequirements"]
                    logger.info("x402.submit: payment_requirements_parsed")
                    debug_ctx(
                        "x402.submit.requirements.ctx",
                        amount_smallest_units=reqs.get("maxAmountRequired"),
                        asset=reqs.get("asset"),
                        pay_to=reqs.get("payTo"),
                        description=reqs.get("description"),
                    )
            # OLD: Fallback for base64 transaction format (facilitator)
            elif "transaction" in payload:
                logger.warning(
                    "x402.submit: old_transaction_format detected=facilitator_based"
                )
            else:
                logger.warning("x402.submit: no_signature_or_transaction")
        else:
            logger.warning("x402.submit: unexpected_payload_structure")

    except json.JSONDecodeError as e:
        logger.error(f"x402.submit: parse_failed error={str(e)[:200]}")
        payment_data = {"raw_payment": payment_header}

    # Verify payment on blockchain (NEW: No facilitator needed!)
    logger.info("x402.submit: starting_blockchain_verification")

    # Check if we have a transaction signature
    if not transaction_signature:
        logger.error("x402.submit: no_transaction_signature")
        raise HTTPException(status_code=402, detail="No transaction signature provided")

    # Replay attack prevention: Check if signature already used
    import time as time_module

    current_time = time_module.time()

    # Clean up expired signatures
    expired = [
        sig
        for sig, timestamp in used_signatures.items()
        if current_time - timestamp > (SIGNATURE_EXPIRY_HOURS * 3600)
    ]
    for sig in expired:
        del used_signatures[sig]

    # Check if this signature was already used
    if transaction_signature in used_signatures:
        used_at = used_signatures[transaction_signature]
        age_minutes = int((current_time - used_at) / 60)
        logger.error(
            f"x402.replay_check: result=used_signature age_minutes={age_minutes}"
        )
        debug_ctx("x402.replay_check.ctx", signature=transaction_signature)
        raise HTTPException(
            status_code=402,
            detail=f"Transaction signature already used {age_minutes} minutes ago. Possible replay attack.",
        )

    logger.info("x402.replay_check: result=passed")

    # Extract payment requirements for verification
    if not payment_data or "paymentRequirements" not in payment_data:
        logger.error("x402.submit: no_payment_requirements")
        raise HTTPException(status_code=402, detail="Invalid payment header format")

    reqs = payment_data["paymentRequirements"]
    expected_amount = int(reqs.get("maxAmountRequired", 0))
    expected_asset = reqs.get("asset", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
    # expected_recipient is already set from receiver.get_payment_address() above

    # Start timing verification
    import time

    verify_start = time.time()

    # NEW: Verify transaction directly on Solana blockchain
    # No timing issues, no facilitator dependency!
    payment_result = await solana_x402.verify_transaction_onchain(
        signature=transaction_signature,
        expected_recipient=expected_recipient,
        expected_amount=expected_amount,
        expected_asset=expected_asset,
    )

    verify_elapsed = int((time.time() - verify_start) * 1000)
    logger.info(f"x402.verify_onchain: result=valid elapsed_ms={verify_elapsed}")
    is_valid = payment_result.get("valid") or payment_result.get("isValid")

    if not is_valid:
        error_msg = payment_result.get("error") or "Invalid payment"
        logger.error(f"x402.verify_onchain: result=invalid error={str(error_msg)}")
        debug_ctx(
            "x402.verify_onchain.error.ctx",
            error=error_msg,
            verify_response=payment_result,
        )
        raise HTTPException(
            status_code=402, detail=f"Payment verification failed: {error_msg}"
        )

    logger.info("x402.verify_onchain: result=valid")
    debug_ctx("x402.verify_onchain.result.ctx", payment_result=payment_result)

    # Extract amount from verified payment
    # Blockchain returns the amount in the token's smallest unit (micro-USDC)
    # We need to convert it back to dollars for display/storage
    verified_amount_smallest_unit = payment_result.get("amount", 0)
    if isinstance(verified_amount_smallest_unit, str):
        verified_amount_smallest_unit = int(verified_amount_smallest_unit)

    # Convert from smallest unit to dollars (6 decimals for USDC)
    verified_amount = float(verified_amount_smallest_unit) / 1_000_000.0
    logger.info(
        f"x402.amount: verified micro_usdc={verified_amount_smallest_unit} usd={verified_amount}"
    )

    # Validate sender name length
    if len(donation_request.sender_name) > MAX_SENDER_NAME_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Sender name too long (max {MAX_SENDER_NAME_LENGTH} chars)",
        )

    # Validate message length
    if len(donation_request.message) > MAX_MESSAGE_LENGTH:
        raise HTTPException(
            status_code=400, detail=f"Message too long (max {MAX_MESSAGE_LENGTH} chars)"
        )

    # receiver is already validated and looked up at the beginning of this function

    # Create new donation record (privacy-first: no wallet/signature data)
    donation = Donation(
        sender_name=donation_request.sender_name[
            :MAX_SENDER_NAME_LENGTH
        ],  # Enforce max length
        message=donation_request.message[
            :MAX_MESSAGE_LENGTH
        ],  # Auto-encrypted by EncryptedString
        amount=verified_amount,  # Use verified payment amount
        token_symbol="USDC",
        receiver_id=receiver.id,  # Multi-user support
        source="x402",
        status="pending",
        # Privacy: These fields are NOT stored (columns removed):
        # - signature (TX hash) - Enables blockchain explorer lookup → deanonymization
        # - sender (wallet) - Direct identity exposure
        # - timestamp - Enables timing correlation attacks
    )

    db.add(donation)
    db.commit()
    db.refresh(donation)

    # Broadcast to dashboard for moderation (only to this receiver's dashboards)
    await broadcast_new_donation(donation.to_dict(), receiver.id)

    # Mark signature as used (replay attack prevention)
    used_signatures[transaction_signature] = current_time
    logger.info("x402.replay_protect: signature_recorded=true")
    debug_ctx("x402.replay_protect.ctx", signature=transaction_signature)

    logger.info(
        f"donation.store: recorded id={donation.id} sender={donation.sender_name} "
        f"amount_usd={donation.amount} has_message={bool(donation.message)}"
    )
    debug_ctx(
        "donation.store.ctx",
        donation_id=donation.id,
        message_preview=(donation.message[:160] if donation.message else ""),
    )

    return {
        "status": "success",
        "donation_id": donation.id,
        "message": "Donation submitted for moderation",
    }


@app.post("/api/wallet-privacy-score")
async def score_wallet_privacy(request: Request):
    """
    Analyze wallet and return privacy score (0-100)

    Request body:
        {
            "wallet": "SOLANA_WALLET_ADDRESS"
        }

    Response:
        {
            "score": 85,
            "grade": "B",
            "risks": ["list of privacy risks"],
            "suggestions": ["list of suggestions"],
            "details": {
                "token_count": 3,
                "protocol_count": 2,
                ...
            }
        }
    """
    try:
        body = await request.json()
        wallet = body.get("wallet")

        if not wallet:
            raise HTTPException(status_code=400, detail="Wallet address required")

        logger.info(f"🔍 Privacy scoring request for wallet: {wallet[:8]}...")

        # Score the wallet
        score = await privacy_scorer.score_wallet(wallet)

        logger.info(f"✅ Privacy score: {score.score}/100 ({score.grade})")

        return score.to_dict()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error scoring wallet: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to score wallet: {str(e)}")


@app.post("/api/helius/rpc")
async def helius_rpc_proxy(request: Request):
    """
    Proxy for Helius RPC calls to keep API key server-side.
    Compatible with Solana web3.js Connection class.

    Security: Required for transaction broadcasting and blockchain queries.
    This endpoint is necessary for the donation flow.

    Request body: JSON-RPC request object (single or batch)
    Response: JSON-RPC response from Helius
    """
    if not helius_client:
        raise HTTPException(status_code=500, detail="helius api not configured")

    try:
        body = await request.json()
        return await helius_client.rpc_call(body)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"helius.rpc.error: {str(e)[:200]}")
        raise HTTPException(status_code=500, detail="rpc proxy error")



# WebSocket endpoints
@app.websocket("/ws")
async def overlay_websocket(websocket: WebSocket):
    """WebSocket for overlay - receives approved donations."""
    await websocket.accept()
    overlay_connections.append(websocket)
    logger.info(f"ws.overlay.connect: total={len(overlay_connections)}")

    try:
        await websocket.send_json({"type": "connected"})

        # Keep alive
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        overlay_connections.remove(websocket)
        logger.info(f"ws.overlay.disconnect: remaining={len(overlay_connections)}")


@app.websocket("/ws/dashboard")
async def dashboard_websocket(websocket: WebSocket, db: Session = Depends(get_db)):
    """WebSocket for dashboard - receives new pending donations (authenticated)."""
    receiver_id = None
    try:
        # Authenticate before accepting connection
        receiver_id = await verify_websocket_auth(websocket, db)

        # Accept connection after authentication succeeds
        await websocket.accept()

        # Add to receiver's connection list
        if receiver_id not in dashboard_connections:
            dashboard_connections[receiver_id] = []
        dashboard_connections[receiver_id].append(websocket)

        # Count total connections across all users
        total_connections = sum(len(conns) for conns in dashboard_connections.values())
        logger.info(
            f"ws.dashboard.connect: receiver_id={receiver_id} total={total_connections}"
        )

        await websocket.send_json({"type": "connected", "receiver_id": receiver_id})

        # Keep alive
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})

    except HTTPException:
        # Authentication failed, connection already closed
        logger.info("ws.dashboard.connect_failed: auth_failed")
        return
    except WebSocketDisconnect:
        # Remove from receiver's connection list
        if receiver_id and receiver_id in dashboard_connections:
            if websocket in dashboard_connections[receiver_id]:
                dashboard_connections[receiver_id].remove(websocket)
            # Clean up empty lists
            if not dashboard_connections[receiver_id]:
                del dashboard_connections[receiver_id]

        total_connections = sum(len(conns) for conns in dashboard_connections.values())
        logger.info(
            f"ws.dashboard.disconnect: receiver_id={receiver_id} remaining={total_connections}"
        )


async def broadcast_to_connections(
    connections: List[WebSocket], message: dict, connection_type: str
) -> None:
    """Generic WebSocket broadcast function - DRY principle."""
    if not connections:
        logger.info(
            f"ws.broadcast.skip: type={connection_type} reason=no_active_connections"
        )
        return

    disconnected = []
    for websocket in connections:
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.info(f"ws.broadcast.error: type={connection_type} error={e}")
            disconnected.append(websocket)

    # Clean up disconnected clients
    for ws in disconnected:
        connections.remove(ws)

    logger.info(f"ws.broadcast.sent: type={connection_type} count={len(connections)}")


async def broadcast_new_donation(donation_data: dict, receiver_id: str):
    """Broadcast new pending donation to specific receiver's dashboards only."""
    # Get connections for this specific receiver
    connections = dashboard_connections.get(receiver_id, [])

    if not connections:
        logger.info(
            f"ws.broadcast.skip: type=dashboards receiver_id={receiver_id} reason=no_connections"
        )
        return

    message = {"type": "new_donation", "data": donation_data}

    disconnected = []
    for websocket in connections:
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.info(f"ws.broadcast.error: type=dashboards error={e}")
            disconnected.append(websocket)

    # Clean up disconnected clients
    for ws in disconnected:
        connections.remove(ws)
    if not connections:
        del dashboard_connections[receiver_id]

    logger.info(
        f"ws.broadcast.sent: type=dashboards receiver_id={receiver_id} count={len(connections)}"
    )


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
                if donation.id not in seen_signatures:
                    seen_signatures.add(donation.id)
                    logger.info(
                        f"donation.monitor: new_pending id={donation.id} sender={donation.sender_name} "
                        f"amount={donation.amount} token={donation.token_symbol}"
                    )
                    # Broadcast to receiver's dashboards only
                    if donation.receiver_id:
                        await broadcast_new_donation(
                            donation.to_dict(), donation.receiver_id
                        )
                    else:
                        # Legacy donation without receiver_id (shouldn't happen with new code)
                        logger.warning(
                            f"donation.monitor: donation_id={donation.id} missing_receiver_id"
                        )

            await asyncio.sleep(2)  # Check every 2 seconds

        except Exception as e:
            logger.error(f"donation.monitor.error: {e}", exc_info=True)
            await asyncio.sleep(5)
        finally:
            if db:
                db.close()


# ============================================================================
# CLI COMMANDS & EXPORT FUNCTIONS
# ============================================================================


def export_donations_json():
    """Export all donations to JSON file for backup."""
    db = SessionLocal()
    try:
        donations = db.query(Donation).order_by(Donation.created_at.desc()).all()

        # Convert to dict format
        export_data = {
            "export_timestamp": datetime.utcnow().isoformat(),
            "total_donations": len(donations),
            "donations": [d.to_dict() for d in donations],
        }

        # Create filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"donations_backup_{timestamp}.json"

        # Write to file
        with open(filename, "w") as f:
            json.dump(export_data, f, indent=2, default=str)

        logger.info(
            f"export.json: success count={len(donations)} file={filename} size_bytes={os.path.getsize(filename)}"
        )

    except Exception as e:
        logger.error(f"export.json: failed error={e}")
    finally:
        db.close()


def export_donations_csv_cli():
    """Export all donations to CSV file for backup (CLI version)."""
    db = SessionLocal()
    try:
        donations = db.query(Donation).order_by(Donation.created_at.desc()).all()

        # Create filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"donations_backup_{timestamp}.csv"

        # Write CSV file
        with open(filename, "w", newline="") as csvfile:
            writer = csv.writer(csvfile)

            # Write header
            writer.writerow(
                [
                    "ID",
                    "Created At",
                    "Sender Name",
                    "Amount",
                    "Token Symbol",
                    "Message",
                    "Status",
                    "Moderated At",
                ]
            )

            # Write data rows
            for donation in donations:
                writer.writerow(
                    [
                        donation.id,
                        donation.created_at.isoformat() if donation.created_at else "",
                        donation.sender_name or "",
                        donation.amount,
                        donation.token_symbol or "",
                        donation.message or "",
                        donation.status,
                        (
                            donation.moderated_at.isoformat()
                            if donation.moderated_at
                            else ""
                        ),
                    ]
                )

        logger.info(
            f"export.csv: success count={len(donations)} file={filename} size_bytes={os.path.getsize(filename)}"
        )

    except Exception as e:
        logger.error(f"export.csv: failed error={e}")
    finally:
        db.close()


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else None

    if not command:
        logger.info("Usage:")
        logger.info("  python app.py init            # Initialize database")
        logger.info("  python app.py sync [days]     # Sync historical donations")
        logger.info("  python app.py recent          # Show recent donations")
        logger.info(
            "  python app.py export-json     # Export all donations to JSON (backup)"
        )
        logger.info(
            "  python app.py export-csv      # Export all donations to CSV (backup)"
        )
        logger.info("  python app.py server          # Start FastAPI server")
        sys.exit(1)

    if command == "init":
        init_db()
        logger.info("server.init: database_initialized")
        return

    if command == "server":
        import uvicorn

        logger.info("server.start: superchat starting")
        logger.info(f"server.start: home_url=http://localhost:{PORT}/")

        uvicorn.run(app, host="0.0.0.0", port=PORT)
        return

    # For recent/export commands, use asyncio
    asyncio.run(cli_async(command))


async def cli_async(command):
    # Initialize database if not init command
    init_db()

    if command == "recent":
        db = SessionLocal()
        try:
            donations = (
                db.query(Donation).order_by(Donation.created_at.desc()).limit(10).all()
            )
            logger.info("📋 Recent donations:")
            for d in donations:
                status_icon = (
                    "✅"
                    if d.status == "approved"
                    else "⏳" if d.status == "pending" else "❌"
                )
                message_preview = f' - "{d.message[:30]}..."' if d.message else ""
                logger.info(
                    f"  {status_icon} ${d.amount:.2f} from {d.sender_name}{message_preview}"
                )
        finally:
            db.close()

    elif command == "export-json":
        export_donations_json()

    elif command == "export-csv":
        export_donations_csv_cli()

    else:
        logger.info(f"❌ Unknown command: {command}")


if __name__ == "__main__":
    main()
