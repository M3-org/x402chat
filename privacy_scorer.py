"""
Wallet Privacy Scorer
Analyzes Solana wallet to assess privacy risks and provide score (0-100)

Can be used standalone or integrated into applications.
"""

import httpx
import time
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class PrivacyScore:
    """Privacy analysis result"""

    score: int  # 0-100
    grade: str  # "A", "B", "C", "D", "F"
    risks: List[str]
    suggestions: List[str]
    details: Dict

    def to_dict(self):
        return asdict(self)


class WalletPrivacyScorer:
    """Analyze Solana wallet privacy using Helius APIs"""

    # Known protocol program IDs and their categories
    PROTOCOL_MAP = {
        # DEX Protocols
        "JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB": {
            "name": "Jupiter",
            "category": "DEX",
        },
        "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc": {
            "name": "Orca",
            "category": "DEX",
        },
        "9W959DqEETiGZocYWCQPaJ6sBmUzgfxXfqGeTEdp3aQP": {
            "name": "Raydium",
            "category": "DEX",
        },
        # NFT Marketplaces
        "M2mx93ekt1fmXSVkTrUL9xVFHkmME8HTUi5Cyc5aF7K": {
            "name": "Magic Eden",
            "category": "NFT_MARKETPLACE",
        },
        "CJsLwbP1iu5DuUikHEJnLfANgKy6stB2uFgvBBHoyxwz": {
            "name": "Solanart",
            "category": "NFT_MARKETPLACE",
        },
        "hadeK9DLv9eA7ya5KCTqSvSvRZeJC3JgD5a9Y3CNbvu": {
            "name": "Tensor",
            "category": "NFT_MARKETPLACE",
        },
        # CEX / Centralized Bridges (high risk for privacy)
        "WoRMXoVLu1xXJc3Mzu8hPHAQ8efqj6xhPJ77Tr2C3zV": {
            "name": "Wormhole",
            "category": "BRIDGE_CEX",
        },
        # Privacy Cash
        "CASHqhUJYu3BqWfXk8SJZ6KwQS2GNJMmZWVRfP5TgZ6j": {
            "name": "Privacy Cash",
            "category": "PRIVACY",
        },
    }

    def __init__(self, helius_api_key: str):
        self.api_key = helius_api_key
        self.base_url = "https://api.helius.xyz/v0"

    async def score_wallet(self, wallet_address: str) -> PrivacyScore:
        """
        Main entry point - analyze wallet and return privacy score

        Args:
            wallet_address: Solana wallet public key

        Returns:
            PrivacyScore with score, grade, risks, and suggestions
        """
        logger.info(f"🔍 Scoring wallet privacy: {wallet_address}")

        try:
            # Gather data from Helius (prefer enhanced txs for OSINT)
            enhanced_txs = await self.get_enhanced_txs(wallet_address, limit=100)

            # Fallback to legacy endpoint if enhanced fails
            if enhanced_txs:
                tx_history = enhanced_txs
            else:
                tx_history = await self.get_transaction_history(
                    wallet_address, limit=100
                )

            tokens = await self.get_tokens(wallet_address)

            # OSINT: Comprehensive pattern analysis
            patterns = self.analyze_transaction_patterns(wallet_address, enhanced_txs)

            # OSINT: Analyze first transaction (funding source)
            first_info = self.analyze_first_funding(wallet_address, enhanced_txs)
            first_ts = first_info["first_ts"]
            privacy_cash_first = first_info["privacy_cash_first"]
            cex_like_first = first_info["cex_like_first"]

            # Detect protocols
            protocols = self.detect_protocols(tx_history)
            protocol_names = [p["name"] for p in protocols]

            # Count recent activity
            recent_txs = self.count_recent_transactions(tx_history, hours=24)

            # Wallet age from patterns (more accurate)
            age_days = patterns["wallet_age_days"]

            # NFT count
            nfts = [t for t in tokens if self._is_nft(t)]
            nft_count = len(nfts)

            # Token diversity
            token_count = len([t for t in tokens if t.get("amount", 0) > 0])

            # Start scoring
            score = 100
            risks = []
            suggestions = []

            # === NEW: First transaction weighting (OSINT signal) ===
            if privacy_cash_first:
                # Wallet was born private - huge bonus
                score += 20
                suggestions.append(
                    "✅ Wallet was initially funded through Privacy Cash (first on-chain action). Strong privacy hygiene from origin."
                )
            elif cex_like_first:
                # Funded from CEX/bridge - major privacy hit
                score -= 30
                risks.append(
                    "⚠️ First inbound funding linked to a centralized / KYC-like source. Wallet origin likely traceable off-chain."
                )
            # else: neutral origin

            # Factor 1: Token diversity (-10 per token type beyond SOL)
            if token_count > 0:
                penalty = min(token_count * 10, 50)
                score -= penalty
                risks.append(f"{token_count} token types held (linkability risk)")
                suggestions.append(
                    "💡 Use dedicated wallets per token/type for better isolation"
                )

            # Factor 2: Protocol interactions
            high_risk_protocols = ["CEX", "KYC", "NFT_MARKETPLACE", "BRIDGE_CEX"]
            for protocol in protocols:
                if protocol["category"] in high_risk_protocols:
                    score -= 20
                    risks.append(
                        f"⚠️ {protocol['name']} interaction detected ({protocol['category']})"
                    )

            if len(protocols) > 0:
                suggestions.append(
                    "💡 Use Privacy Cash to break on-chain links between identities"
                )

            # Factor 3: Transaction volume (recent activity risk)
            if recent_txs > 10:
                score -= 15
                risks.append(
                    f"⚠️ {recent_txs} transactions in last 24h (timing correlation risk)"
                )
                suggestions.append(
                    "💡 Wait ~24h between Privacy Cash deposit and withdrawal"
                )

            # Factor 4: NFT holdings (identity exposure)
            if nft_count > 0:
                score -= 25
                risks.append(
                    f"⚠️ {nft_count} NFTs detected (potential identity fingerprint)"
                )
                suggestions.append(
                    "💡 Use a separate wallet for NFTs vs donations/spend"
                )

            # Factor 5: Wallet age / cleanliness (bonus for fresh wallets)
            if age_days < 7 and len(tx_history) < 5:
                score += 10
                suggestions.append("✅ Very fresh wallet with minimal history")

            # Factor 6: Privacy Cash usage (non-first use bonus)
            PRIVACY_CASH_PID = "CASHqhUJYu3BqWfXk8SJZ6KwQS2GNJMmZWVRfP5TgZ6j"
            if not privacy_cash_first and "Privacy Cash" in protocol_names:
                score += 5
                suggestions.append("✅ Privacy Cash detected in history")

            # Factor 7: Hub behavior detection (many unique counterparties = privacy risk)
            if patterns["unique_counterparties"] > 20:
                score -= 10
                risks.append(
                    f"⚠️ {patterns['unique_counterparties']} unique counterparties (hub-like behavior)"
                )
                suggestions.append(
                    "💡 Avoid using single wallet for many different recipients"
                )

            # Factor 8: High swap activity (DEX power user = more metadata)
            if patterns["swap_count"] > 10:
                score -= 5
                risks.append(
                    f"⚠️ {patterns['swap_count']} swaps detected (DEX power user)"
                )

            # Factor 9: NFT trading activity (marketplace fingerprinting)
            if patterns["nft_purchase_count"] > 5 or patterns["nft_sale_count"] > 3:
                score -= 10
                total_nft_activity = (
                    patterns["nft_purchase_count"] + patterns["nft_sale_count"]
                )
                risks.append(
                    f"⚠️ {total_nft_activity} NFT marketplace transactions (trading fingerprint)"
                )

            # Factor 10: Dormant wallet bonus
            if patterns["dormancy_days"] > 30:
                score += 5
                suggestions.append(
                    f"✅ Wallet dormant for {patterns['dormancy_days']} days (reduced correlation risk)"
                )

            # Factor 11: Excessive activity penalty (very high tx/day = automation/bot)
            if patterns["avg_tx_per_day"] > 5:
                score -= 10
                risks.append(
                    f"⚠️ High activity: {patterns['avg_tx_per_day']} tx/day average (automation pattern)"
                )

            # Clamp score to 0-100 range
            score = max(0, min(100, score))

            logger.info(f"✅ Privacy score: {score}/100 ({self.score_to_grade(score)})")

            return PrivacyScore(
                score=score,
                grade=self.score_to_grade(score),
                risks=risks,
                suggestions=suggestions,
                details={
                    # Token & protocol metrics
                    "token_count": token_count,
                    "protocol_count": len(protocols),
                    "protocols": protocol_names,
                    "nft_count": nft_count,
                    # Transaction patterns (NEW)
                    "total_transactions": patterns["total_txs"],
                    "outgoing_transactions": patterns["outgoing_txs"],
                    "incoming_transactions": patterns["incoming_txs"],
                    "swap_count": patterns["swap_count"],
                    "nft_purchases": patterns["nft_purchase_count"],
                    "nft_sales": patterns["nft_sale_count"],
                    "unique_counterparties": patterns["unique_counterparties"],
                    # Activity metrics (NEW)
                    "recent_tx_count_24h": recent_txs,
                    "avg_transactions_per_day": patterns["avg_tx_per_day"],
                    "dormancy_days": patterns["dormancy_days"],
                    "wallet_age_days": age_days,
                    # Origin analysis
                    "first_tx_privacy_cash": privacy_cash_first,
                    "first_tx_cex_like": cex_like_first,
                    "first_seen_unix": first_ts,
                },
            )

        except Exception as e:
            logger.error(f"❌ Error scoring wallet: {e}")
            # Return default score on error
            return PrivacyScore(
                score=50,
                grade="C",
                risks=["Unable to fully analyze wallet"],
                suggestions=["Analysis incomplete - use caution"],
                details={"error": str(e)},
            )

    async def get_enhanced_txs(
        self, wallet_address: str, limit: int = 100
    ) -> List[Dict]:
        """
        Get decoded/enhanced transactions for a wallet (OSINT-optimized).
        Uses Helius Enhanced Transactions API for pre-parsed instructions.
        """
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{self.base_url}/addresses/{wallet_address}/transactions",
                    params={"api-key": self.api_key, "limit": limit},
                )
                response.raise_for_status()
                data = response.json()
                return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning(f"⚠️ Failed to fetch enhanced txs: {e}")
            return []

    async def get_tokens(self, wallet_address: str) -> List[Dict]:
        """Get all tokens held by wallet using Helius DAS API"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/addresses/{wallet_address}/balances",
                    params={"api-key": self.api_key},
                )
                response.raise_for_status()
                data = response.json()
                return data.get("tokens", [])
        except Exception as e:
            logger.warning(f"⚠️ Failed to fetch tokens: {e}")
            return []

    async def get_transaction_history(
        self, wallet_address: str, limit: int = 100
    ) -> List[Dict]:
        """Get recent transaction history"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/addresses/{wallet_address}/transactions",
                    params={"api-key": self.api_key, "limit": limit},
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.warning(f"⚠️ Failed to fetch transaction history: {e}")
            return []

    def analyze_transaction_patterns(
        self, wallet_address: str, enhanced_txs: List[Dict]
    ) -> Dict:
        """
        Comprehensive transaction pattern analysis for privacy scoring.

        Returns detailed metrics about wallet behavior patterns.
        """
        if not enhanced_txs:
            return {
                "total_txs": 0,
                "outgoing_txs": 0,
                "incoming_txs": 0,
                "swap_count": 0,
                "nft_purchase_count": 0,
                "nft_sale_count": 0,
                "unique_counterparties": 0,
                "avg_tx_per_day": 0,
                "dormancy_days": 0,
            }

        outgoing_txs = 0
        incoming_txs = 0
        swap_count = 0
        nft_purchases = 0
        nft_sales = 0
        counterparties = set()

        for tx in enhanced_txs:
            # Analyze native transfers (SOL)
            for transfer in tx.get("nativeTransfers", []):
                if transfer.get("fromUserAccount") == wallet_address:
                    outgoing_txs += 1
                    if transfer.get("toUserAccount"):
                        counterparties.add(transfer["toUserAccount"])
                elif transfer.get("toUserAccount") == wallet_address:
                    incoming_txs += 1
                    if transfer.get("fromUserAccount"):
                        counterparties.add(transfer["fromUserAccount"])

            # Analyze token transfers
            for transfer in tx.get("tokenTransfers", []):
                if transfer.get("fromUserAccount") == wallet_address:
                    outgoing_txs += 1
                    if transfer.get("toUserAccount"):
                        counterparties.add(transfer["toUserAccount"])
                elif transfer.get("toUserAccount") == wallet_address:
                    incoming_txs += 1
                    if transfer.get("fromUserAccount"):
                        counterparties.add(transfer["fromUserAccount"])

            # Detect swaps
            if tx.get("events", {}).get("swap"):
                swap_count += 1

            # Detect NFT activity
            nft_event = tx.get("events", {}).get("nft", {})
            if nft_event:
                event_type = nft_event.get("type", "")
                if (
                    event_type in ["NFT_SALE", "NFT_BID"]
                    and nft_event.get("buyer") == wallet_address
                ):
                    nft_purchases += 1
                elif (
                    event_type == "NFT_SALE"
                    and nft_event.get("seller") == wallet_address
                ):
                    nft_sales += 1

        # Calculate activity metrics
        if enhanced_txs:
            oldest_ts = min(
                tx.get("timestamp", 0) for tx in enhanced_txs if tx.get("timestamp")
            )
            newest_ts = max(
                tx.get("timestamp", 0) for tx in enhanced_txs if tx.get("timestamp")
            )
            age_days = (time.time() - oldest_ts) / 86400 if oldest_ts else 0

            # Dormancy: days since last transaction
            dormancy_days = (time.time() - newest_ts) / 86400 if newest_ts else 0

            # Average transactions per day
            avg_tx_per_day = len(enhanced_txs) / age_days if age_days > 0 else 0
        else:
            age_days = 0
            dormancy_days = 0
            avg_tx_per_day = 0

        return {
            "total_txs": len(enhanced_txs),
            "outgoing_txs": outgoing_txs,
            "incoming_txs": incoming_txs,
            "swap_count": swap_count,
            "nft_purchase_count": nft_purchases,
            "nft_sale_count": nft_sales,
            "unique_counterparties": len(counterparties),
            "avg_tx_per_day": round(avg_tx_per_day, 2),
            "dormancy_days": int(dormancy_days),
            "wallet_age_days": int(age_days),
        }

    def analyze_first_funding(
        self, wallet_address: str, enhanced_txs: List[Dict]
    ) -> Dict:
        """
        OSINT-style analysis: how did this wallet 'enter the graph'?

        Returns:
            {
              "first_tx_sig": str | None,
              "first_ts": int | None,
              "first_program_ids": set([...]),
              "funders": set([...]),   # other accounts in that tx
              "privacy_cash_first": bool,
              "cex_like_first": bool
            }
        """
        if not enhanced_txs:
            return {
                "first_tx_sig": None,
                "first_ts": None,
                "first_program_ids": set(),
                "funders": set(),
                "privacy_cash_first": False,
                "cex_like_first": False,
            }

        # Find oldest transaction by timestamp
        def _ts(tx):
            return tx.get("blockTime") or tx.get("timestamp") or 0

        oldest = min(enhanced_txs, key=_ts)
        first_ts = _ts(oldest)
        first_sig = oldest.get("signature")

        # Collect all program IDs in first transaction
        first_program_ids = set()
        for instr in oldest.get("instructions", []):
            pid = instr.get("programId") or instr.get("program")
            if pid:
                first_program_ids.add(pid)
        for instr in oldest.get("innerInstructions", []):
            pid = instr.get("programId") or instr.get("program")
            if pid:
                first_program_ids.add(pid)

        # Collect counterparties (other accounts in first tx)
        funders = set()
        for key in oldest.get("accountKeys", []):
            if key != wallet_address:
                funders.add(key)

        # Classification
        PRIVACY_CASH_PID = "CASHqhUJYu3BqWfXk8SJZ6KwQS2GNJMmZWVRfP5TgZ6j"
        privacy_cash_first = PRIVACY_CASH_PID in first_program_ids

        # CEX-like detection: first tx uses CEX/KYC/bridge programs
        cex_like_first = False
        for pid in first_program_ids:
            meta = self.PROTOCOL_MAP.get(pid)
            if meta and meta.get("category") in (
                "CEX",
                "KYC",
                "CUSTODIAL",
                "BRIDGE_CEX",
            ):
                cex_like_first = True
                break

        return {
            "first_tx_sig": first_sig,
            "first_ts": first_ts,
            "first_program_ids": first_program_ids,
            "funders": funders,
            "privacy_cash_first": privacy_cash_first,
            "cex_like_first": cex_like_first,
        }

    def detect_protocols(self, tx_history: List[Dict]) -> List[Dict]:
        """Detect which protocols wallet has interacted with"""
        protocols = {}

        for tx in tx_history:
            # Check each instruction for known program IDs
            for instruction in tx.get("instructions", []):
                program_id = instruction.get("programId")
                if program_id and program_id in self.PROTOCOL_MAP:
                    protocols[program_id] = self.PROTOCOL_MAP[program_id]

        return list(protocols.values())

    def count_recent_transactions(self, tx_history: List[Dict], hours: int = 24) -> int:
        """Count transactions in last N hours"""
        cutoff = time.time() - (hours * 3600)
        count = 0

        for tx in tx_history:
            timestamp = tx.get("timestamp")
            if timestamp and timestamp > cutoff:
                count += 1

        return count

    def get_wallet_age_days(self, tx_history: List[Dict]) -> int:
        """Calculate wallet age from first transaction"""
        if not tx_history:
            return 0

        # Find oldest transaction
        oldest_timestamp = None
        for tx in tx_history:
            timestamp = tx.get("timestamp")
            if timestamp:
                if oldest_timestamp is None or timestamp < oldest_timestamp:
                    oldest_timestamp = timestamp

        if oldest_timestamp is None:
            return 0

        age_seconds = time.time() - oldest_timestamp
        return int(age_seconds / 86400)

    def _is_nft(self, token: Dict) -> bool:
        """Check if token is an NFT (heuristic: amount = 1, decimals = 0)"""
        amount = token.get("amount", 0)
        decimals = token.get("decimals", 6)
        return amount == 1 and decimals == 0

    @staticmethod
    def score_to_grade(score: int) -> str:
        """Convert numeric score to letter grade"""
        if score >= 90:
            return "A"
        elif score >= 75:
            return "B"
        elif score >= 60:
            return "C"
        elif score >= 40:
            return "D"
        else:
            return "F"


# Standalone usage example
if __name__ == "__main__":
    import asyncio
    import os
    import argparse

    parser = argparse.ArgumentParser(description="Analyze Solana wallet privacy")
    parser.add_argument("wallet", help="Solana wallet address to analyze")
    parser.add_argument(
        "--api-key", help="Helius API key (or set HELIUS_API_KEY env var)", default=None
    )
    args = parser.parse_args()

    async def main():
        api_key = args.api_key or os.getenv("HELIUS_API_KEY")
        if not api_key:
            print(
                "Error: HELIUS_API_KEY environment variable not set and --api-key not provided"
            )
            print("\nUsage:")
            print("  python privacy_scorer.py <wallet_address>")
            print("  python privacy_scorer.py <wallet_address> --api-key <your_key>")
            return

        scorer = WalletPrivacyScorer(api_key)

        print(f"\n🔍 Analyzing wallet: {args.wallet[:8]}...{args.wallet[-8:]}")
        result = await scorer.score_wallet(args.wallet)

        print(f"\n{'='*50}")
        print(f"Wallet Privacy Score: {result.score}/100 ({result.grade})")
        print(f"{'='*50}\n")

        if result.risks:
            print("⚠️  Privacy Risks:")
            for risk in result.risks:
                print(f"  - {risk}")
            print()

        if result.suggestions:
            print("💡 Suggestions:")
            for suggestion in result.suggestions:
                print(f"  - {suggestion}")
            print()

        print("📊 Details:")
        for key, value in result.details.items():
            print(f"  {key}: {value}")

    asyncio.run(main())
