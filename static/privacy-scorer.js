/**
 * Client-Side Wallet Privacy Scorer
 *
 * Security update: Simplified to use server-side /api/wallet-privacy-score endpoint.
 * Previous client-side implementation removed to prevent exposing Helius API endpoints.
 *
 * The server-side implementation (privacy_scorer.py) performs comprehensive OSINT analysis
 * with proper rate limiting and security controls.
 */

const API_BASE = window.location.origin;

// Note: The following helper functions have been removed as they are no longer needed:
// - getWalletHighLevelStats() - RPC calls now server-side only
// - getEnhancedTransactions() - Helius API endpoint removed for security
// - getEnhancedTransactionsBySignatures() - Helius API endpoint removed for security
// - getTokenBalances() - Helius API endpoint removed for security
// - analyzeTransfers() - Analysis moved server-side
// - analyzeTransactionPatterns() - Analysis moved server-side
// - analyzeFirstFunding() - Analysis moved server-side
// - detectProtocols() - Analysis moved server-side
//
// All privacy analysis logic is now in privacy_scorer.py for better security.

/**
 * Main scoring function - Uses server-side API for security
 *
 * Security improvement: Replaced client-side OSINT with server-side API call.
 * This prevents:
 * - Exposing raw Helius API endpoints to arbitrary queries
 * - Client-side wallet address transmission for privacy checks
 * - Potential abuse of Helius API quota
 *
 * The server-side implementation (privacy_scorer.py) performs the same
 * comprehensive analysis but with better security controls.
 */
export async function scoreWalletPrivacy(walletAddress) {
  // Input validation
  if (!walletAddress || typeof walletAddress !== "string") {
    throw new Error("invalid wallet address: must be a string");
  }

  // Basic Solana address validation (base58, 32-44 characters)
  if (!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(walletAddress)) {
    throw new Error("invalid solana address format");
  }

  console.log(
    "🔍 analyzing wallet privacy:",
    walletAddress.slice(0, 8) + "...",
  );

  try {
    // Call server-side privacy scoring endpoint
    const response = await fetch(`${API_BASE}/api/wallet-privacy-score`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ wallet: walletAddress }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`server error: ${response.status} ${errorText}`);
    }

    const result = await response.json();

    console.log(`✅ privacy score: ${result.score}/100 (${result.grade})`);

    return result;
  } catch (error) {
    console.error("❌ error scoring wallet:", error);
    return {
      score: 50,
      grade: "C",
      risks: ["unable to analyze wallet"],
      suggestions: ["analysis incomplete - use caution"],
      details: { error: error.message },
    };
  }
}
