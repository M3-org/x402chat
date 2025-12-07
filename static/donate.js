import {
  ComputeBudgetProgram,
  Connection,
  PublicKey,
  Transaction,
  TransactionMessage,
  VersionedTransaction,
} from "https://esm.sh/@solana/web3.js@1.95.3";
import {
  createAssociatedTokenAccountInstruction,
  createTransferCheckedInstruction,
  getAssociatedTokenAddressSync,
} from "https://esm.sh/@solana/spl-token@0.4.9";
import { scoreWalletPrivacy } from "/privacy-scorer.js";
import { escapeHtml, escapeAttr } from '/security-utils.js';

// Fix secure context issue: redirect 0.0.0.0 to localhost
if (window.location.hostname === "0.0.0.0") {
  console.log(
    "⚠️ Redirecting from 0.0.0.0 to localhost (Phantom requires secure context)",
  );
  const newUrl = window.location.href.replace("0.0.0.0", "localhost");
  window.location.replace(newUrl);
}

const $ = (id) => document.getElementById(id);
const API_BASE = window.location.origin;

// Extract identifier from URL path (/donate/{identifier})
// Can be either username or receiver_id
const IDENTIFIER = window.location.pathname.split("/").pop();
if (!IDENTIFIER) {
  console.error("❌ No identifier in URL path");
  throw new Error("Invalid donation page URL");
}
console.log(`📋 Identifier: ${IDENTIFIER}`);
const DONATE_URL = `${API_BASE}/api/donate/${IDENTIFIER}`;

const set = (el, msg) => (el.textContent = msg);
const setHTML = (el, msg) => (el.innerHTML = msg);
const show = (msg) => set($("status"), msg);
const ok = (msg) => {
  $("success").classList.remove("hidden");
  setHTML($("success"), msg);
  $("error").classList.add("hidden");
};
const err = (msg) => {
  $("error").classList.remove("hidden");
  set($("error"), msg);
  $("success").classList.add("hidden");
};

// Load receiver info and set default amount
async function loadReceiverInfo() {
  try {
    const response = await fetch(`${API_BASE}/api/receiver/${IDENTIFIER}`);
    if (response.ok) {
      const data = await response.json();
      // Set default donation amount
      if (data.default_donation_amount) {
        $("amount").value = data.default_donation_amount;
      }
      console.log(`✅ Loaded default amount: ${data.default_donation_amount}`);
    }
  } catch (error) {
    console.warn("⚠️ Could not load receiver info:", error);
    // Keep hardcoded default if API fails
  }
}

// Load receiver info on page load
loadReceiverInfo();

async function getChallenge(payload) {
  const res = await fetch(DONATE_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (res.status !== 402) {
    const t = await res.text();
    throw new Error(`Expected 402, got ${res.status}: ${t}`);
  }
  const j = await res.json();
  const acc = j?.detail?.accepts?.[0];
  if (!acc) throw new Error("No x402 accepts returned");
  return acc; // { network, asset, payTo, amount, description }
}

function toBase64(u8) {
  // stable base64 for big Uint8Arrays
  let s = "";
  const cs = 0x8000;
  for (let i = 0; i < u8.length; i += cs) {
    s += String.fromCharCode.apply(null, u8.subarray(i, i + cs));
  }
  return btoa(s);
}

async function analyzeWalletPrivacy(walletAddress) {
  try {
    show("Analyzing wallet privacy…");

    // Call client-side scorer - wallet address never sent to our server!
    const score = await scoreWalletPrivacy(walletAddress);

    if (score) {
      currentPrivacyScore = score; // Store globally for private tip gating
      displayPrivacyScore(score);
      console.log(
        "✅ Privacy analysis complete (queries via Helius API, wallet not sent to our server)",
      );
    }

    return score;
  } catch (e) {
    console.error("Privacy scoring error:", e);
    return null;
  }
}

function displayPrivacyScore(score) {
  const scoreCard = $("privacyScoreCard");
  if (!scoreCard) return;

  scoreCard.classList.remove("hidden");
  scoreCard.className = `privacy-score grade-${score.grade}`;

  let html = `
    <div class="score-header">
      <h3>Wallet Privacy Score: ${score.score}/100 <span class="grade-badge">${score.grade}</span></h3>
    </div>
  `;

  // Add disclosure and guidance based on score
  if (score.score < 70) {
    html += `
      <div class="privacy-warning">
        <p><strong>⚠️ What This Tip Reveals On-Chain:</strong></p>
        <p class="muted" style="font-size: 0.9rem;">
          Your wallet address, transaction history, token holdings, and potential links to exchanges or other identities.
        </p>
        <p class="muted" style="font-size: 0.9rem; margin-top: 0.5rem;">
          <strong>Want more privacy?</strong>
          <a href="https://www.privacycash.org/" target="_blank" rel="noopener noreferrer">Create a clean wallet</a>
          and wait 3+ days before tipping. This breaks timing correlations.
        </p>
      </div>
    `;
  } else if (score.score >= 70 && score.score < 90) {
    html += `
      <div class="privacy-info-box">
        <p class="muted" style="font-size: 0.9rem;">
          ✓ Your wallet has reasonable privacy. Tipping from this wallet reveals less than average.
        </p>
      </div>
    `;
  } else {
    html += `
      <div class="privacy-info-box">
        <p class="muted" style="font-size: 0.9rem;">
          ✅ Excellent wallet privacy! Safe to tip from this wallet.
        </p>
      </div>
    `;
  }

  if (score.risks && score.risks.length > 0) {
    html += `
      <div class="risks">
        <strong>⚠️ Privacy Risks:</strong>
        <ul>
          ${score.risks.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}
        </ul>
      </div>
    `;
  }

  if (score.suggestions && score.suggestions.length > 0) {
    html += `
      <div class="suggestions">
        <strong>Recommendations:</strong>
        <ul>
          ${score.suggestions.map((s) => `<li>${escapeHtml(s)}</li>`).join("")}
        </ul>
        <p style="margin-top: 0.5rem;">
          <a href="https://www.privacycash.org/" target="_blank" rel="noopener noreferrer">
            Learn more about Privacy Cash →
          </a>
        </p>
      </div>
    `;
  }

  html += `
    <details class="score-details">
      <summary>📊 View All Grading Factors</summary>

      <div class="detail-section">
        <strong>🔍 OSINT - First Transaction Analysis:</strong>
        <ul>
          ${
    score.details.first_tx_privacy_cash
      ? "<li>✅ Born via Privacy Cash (strong origin privacy)</li>"
      : score.details.first_tx_cex_like
      ? "<li>⚠️ Funded from CEX/bridge (KYC-linked origin)</li>"
      : "<li>Origin: Unknown/Organic</li>"
  }
          ${
    score.details.first_tx_signature
      ? `<li>First tx: <code>${
        score.details.first_tx_signature.slice(0, 8)
      }...</code></li>`
      : ""
  }
        </ul>
      </div>

      <div class="detail-section">
        <strong>📈 Wallet History (Accurate Stats):</strong>
        <ul>
          <li><strong>Total transactions:</strong> ${
    score.details.total_transactions || 0
  }</li>
          <li><strong>Wallet age:</strong> ${
    score.details.wallet_age_days || 0
  } days</li>
          <li><strong>Last active:</strong> ${
    score.details.dormancy_days || 0
  } days ago</li>
          <li>Average: ${
    score.details.avg_transactions_per_day || 0
  } tx/day</li>
          <li>Recent activity (24h): ${
    score.details.recent_tx_count_24h || 0
  } txs</li>
        </ul>
      </div>

      <div class="detail-section">
        <strong>💼 Assets & Holdings:</strong>
        <ul>
          <li><strong>Token types held:</strong> ${
    score.details.token_count || 0
  }</li>
          <li><strong>NFTs held:</strong> ${score.details.nft_count || 0}</li>
          <li>NFT purchases: ${score.details.nft_purchases || 0}</li>
          <li>NFT sales: ${score.details.nft_sales || 0}</li>
        </ul>
      </div>

      <div class="detail-section">
        <strong>🔗 Protocol Interactions:</strong>
        <ul>
          <li><strong>Protocols used:</strong> ${
    score.details.protocol_count || 0
  }</li>
          ${
    score.details.protocols && score.details.protocols.length > 0
      ? `<li>Detected: ${score.details.protocols.join(", ")}</li>`
      : "<li>No known protocols detected</li>"
  }
          <li>DEX swaps: ${score.details.swap_count || 0}</li>
          <li>Unique counterparties: ${
    score.details.unique_counterparties || 0
  }</li>
        </ul>
      </div>

      <div class="detail-section">
        <strong>⚙️ Analysis Metadata:</strong>
        <ul>
          <li>Method: Speed-run OSINT (30s)</li>
          <li>Transactions analyzed: ${
    score.details.transactions_analyzed || 0
  }</li>
          <li>Stats accuracy: ${
    score.details.total_transactions >= 1000
      ? "≥1000 (capped)"
      : "Complete history"
  }</li>
        </ul>
      </div>
    </details>
  `;

  scoreCard.innerHTML = html;
}

async function payWithPhantom(event) {
  event.preventDefault();

  try {
    const provider = window?.phantom?.solana;
    if (!provider?.isPhantom) {
      throw new Error("Phantom not found.");
    }

    show("Connecting wallet…");
    const { publicKey } = await provider.connect();

    // Analyze wallet privacy after connection
    await analyzeWalletPrivacy(publicKey.toString());

    const payload = {
      sender_name: $("senderName").value || "anon",
      message: $("message").value || "",
      amount: parseFloat($("amount").value || "0.01"),
      receiver_id: IDENTIFIER, // Server will resolve username → receiver_id
    };

    show("Requesting x402 challenge…");
    const accept = await getChallenge(payload);
    if ((accept.network || "").toLowerCase() !== "solana") {
      throw new Error(
        `Server expects network=${accept.network}. Set X402_NETWORK=solana.`,
      );
    }

    // Use server-side proxied Helius RPC to keep API key secure
    // The server will add the API key before forwarding to Helius
    // Disable WebSocket since our proxy only handles HTTP
    const conn = new Connection(
      `${API_BASE}/api/helius/rpc`,
      {
        commitment: "confirmed",
        wsEndpoint: undefined, // Disable WebSocket, use HTTP polling only
      },
    );
    const mint = new PublicKey(accept.asset); // USDC mint
    const merchantOwner = new PublicKey(accept.payTo);
    const payer = new PublicKey(publicKey.toString());

    // Prevent self-donations
    if (payer.equals(merchantOwner)) {
      throw new Error(
        "You cannot donate to yourself! Please donate to a different creator.",
      );
    }

    const payerAta = getAssociatedTokenAddressSync(mint, payer);
    const merchAta = getAssociatedTokenAddressSync(mint, merchantOwner);

    // The server now sends amount in smallest units (micro-USDC)
    // accept.amount is a string like "10000" for 0.01 USDC
    const amount = parseInt(accept.amount, 10);
    if (isNaN(amount) || amount <= 0) {
      throw new Error("Invalid amount received from server: " + accept.amount);
    }

    console.log("🔍 Transaction details:");
    console.log("  Payer (you):", payer.toString());
    console.log("  Payer ATA:", payerAta.toString());
    console.log("  Merchant:", merchantOwner.toString());
    console.log("  Merchant ATA:", merchAta.toString());
    console.log(
      "  Amount:",
      amount,
      "micro-USDC (=" + amount / 1_000_000 + " USDC)",
    );

    // Check if merchant ATA exists first
    const merchAtaInfo = await conn.getAccountInfo(merchAta);

    if (!merchAtaInfo) {
      // Facilitator's "exact" Solana validator rejects multi-instruction txs.
      // That means we CANNOT include ATA creation in the same transaction.
      // The streamer must pre-create their USDC ATA once before accepting donations.
      throw new Error(
        "Receiver USDC token account doesn't exist yet. " +
          "The streamer needs to receive USDC to this wallet at least once " +
          "to initialize their USDC token account before accepting donations.",
      );
    }

    // Check if payer (user) has sufficient USDC balance
    show("Checking your USDC balance…");
    const payerAtaInfo = await conn.getAccountInfo(payerAta);
    if (!payerAtaInfo) {
      throw new Error(
        "You don't have a USDC account yet. Get some USDC first at https://phantom.app",
      );
    }

    const payerBalance = await conn.getTokenAccountBalance(payerAta);
    const balance = parseInt(payerBalance.value.amount);

    console.log(
      "💰 Your USDC balance:",
      balance,
      "micro-USDC (=" + balance / 1_000_000 + " USDC)",
    );
    console.log(
      "💸 Required amount:",
      amount,
      "micro-USDC (=" + amount / 1_000_000 + " USDC)",
    );
    console.log("✅ Sufficient funds:", balance >= amount);

    if (balance < amount) {
      throw new Error(
        `Insufficient USDC: need ${amount / 1_000_000} USDC, have ${
          balance / 1_000_000
        } USDC`,
      );
    }

    // CRITICAL: x402 'exact' scheme requires EXACTLY 3 instructions (from facilitator source code)
    // Instruction 0: SetComputeUnitLimit (increased to 400k for safety)
    // Instruction 1: SetComputeUnitPrice
    // Instruction 2: TransferChecked (NOT Transfer!)
    // See: x402-rs/src/chain/solana.rs verify_transfer() function
    //
    // Facilitator expects TransferChecked which includes decimals validation
    const decimals = 6; // USDC has 6 decimals

    const computeBudgetIx = [
      ComputeBudgetProgram.setComputeUnitLimit({ units: 400000 }), // Increased from 200k
      ComputeBudgetProgram.setComputeUnitPrice({ microLamports: 0 }),
    ];

    // Use TransferChecked (not Transfer!) - facilitator validates this specifically
    const transferIx = createTransferCheckedInstruction(
      payerAta, // source
      mint, // mint (USDC)
      merchAta, // destination
      payer, // owner
      amount, // amount in smallest units
      decimals, // USDC decimals
    );

    const allInstructions = [...computeBudgetIx, transferIx]; // Exactly 3 instructions

    // Validate instruction structure matches facilitator expectations
    console.log(
      "🔍 Validating instruction structure against facilitator requirements:",
    );
    console.log("  Instruction count:", allInstructions.length, "(must be 3)");

    if (allInstructions.length !== 3) {
      throw new Error(
        `Facilitator expects exactly 3 instructions, got ${allInstructions.length}`,
      );
    }

    // Validate instruction 0: ComputeUnitLimit
    const computeLimit = allInstructions[0];
    console.log(
      "  [0] ComputeLimit program:",
      computeLimit.programId.toString(),
    );
    if (
      computeLimit.programId.toString() !==
        "ComputeBudget111111111111111111111111111111"
    ) {
      throw new Error(
        "Instruction 0 must be ComputeBudget::SetComputeUnitLimit",
      );
    }

    // Validate instruction 1: ComputeUnitPrice
    const computePrice = allInstructions[1];
    console.log(
      "  [1] ComputePrice program:",
      computePrice.programId.toString(),
    );
    if (
      computePrice.programId.toString() !==
        "ComputeBudget111111111111111111111111111111"
    ) {
      throw new Error(
        "Instruction 1 must be ComputeBudget::SetComputeUnitPrice",
      );
    }

    // Validate ComputePrice instruction format (facilitator checks this!)
    const priceData = computePrice.data;
    console.log("      Opcode:", priceData[0], "(must be 3)");
    console.log("      Data length:", priceData.length, "(must be 9)");

    if (priceData[0] !== 3) {
      throw new Error(
        `Invalid ComputePrice opcode: ${priceData[0]} (expected 3)`,
      );
    }
    if (priceData.length !== 9) {
      throw new Error(
        `Invalid ComputePrice data length: ${priceData.length} (expected 9)`,
      );
    }

    // Extract and validate microlamports price (must be ≤ 5,000,000 per facilitator)
    const priceBuf = priceData.slice(1);
    const dataView = new DataView(
      priceBuf.buffer,
      priceBuf.byteOffset,
      priceBuf.byteLength,
    );
    const microlamports = Number(dataView.getBigUint64(0, true));
    console.log(
      "      Compute price:",
      microlamports,
      "microlamports (max 5,000,000)",
    );

    if (microlamports > 5_000_000) {
      throw new Error(
        `Compute price ${microlamports} exceeds facilitator limit of 5,000,000 microlamports`,
      );
    }

    // Validate instruction 2: TransferChecked
    const transfer = allInstructions[2];
    console.log(
      "  [2] TransferChecked program:",
      transfer.programId.toString(),
    );
    if (
      transfer.programId.toString() !==
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
    ) {
      throw new Error("Instruction 2 must be SPL Token TransferChecked");
    }

    console.log("✅ Instruction structure valid for facilitator");

    // Start timing the critical path
    const timingStart = performance.now();
    const timing = { start: timingStart };

    show("Getting fresh blockhash…");
    // CRITICAL: Get blockhash as late as possible with "confirmed" commitment
    // Facilitator simulates with replace_recent_blockhash: false (uses exact blockhash)
    // If blockhash is stale (>150 slots old), simulation fails
    // "confirmed" is fresher than "finalized" (~1-2 sec vs ~32 sec)
    const blockhashStart = performance.now();
    const { blockhash } = await conn.getLatestBlockhash("confirmed");
    timing.blockhash = Math.round(performance.now() - blockhashStart);
    console.log(`⏱️  Blockhash fetch: ${timing.blockhash}ms`);

    show("Building transaction…");
    // Build transaction with our own compute budget instructions
    // Phantom will NOT add more because we already have them
    const buildStart = performance.now();
    const messageV0 = new TransactionMessage({
      payerKey: payer,
      recentBlockhash: blockhash,
      instructions: allInstructions,
    }).compileToV0Message();

    const txV0 = new VersionedTransaction(messageV0);
    timing.build = Math.round(performance.now() - buildStart);
    console.log(`⏱️  Transaction build: ${timing.build}ms`);

    show("Signing transaction…");
    const signStart = performance.now();
    const signed = await provider.signTransaction(txV0);
    const raw = signed.serialize();
    timing.sign = Math.round(performance.now() - signStart);
    console.log(`⏱️  Phantom signing: ${timing.sign}ms`);

    // NEW APPROACH: Broadcast transaction FIRST (no timing pressure)
    // Then verify on-chain (no blockhash staleness issues)
    show("Broadcasting transaction to Solana…");
    const broadcastStart = performance.now();
    const signature = await conn.sendRawTransaction(raw, {
      skipPreflight: false,
    });
    timing.broadcast = Math.round(performance.now() - broadcastStart);
    console.log(`✅ Transaction broadcasted: ${signature}`);
    console.log(`⏱️  Broadcast time: ${timing.broadcast}ms`);

    // Wait for on-chain confirmation using HTTP polling (no WebSocket needed)
    show("Waiting for blockchain confirmation…");
    const confirmStart = performance.now();

    // Poll for confirmation using getSignatureStatuses (works with HTTP-only RPC)
    const maxAttempts = 30; // 30 seconds max wait
    const pollInterval = 1000; // 1 second between polls
    let confirmed = false;

    for (let i = 0; i < maxAttempts; i++) {
      const statusRes = await conn.getSignatureStatuses([signature]);
      const status = statusRes?.value?.[0];

      if (status?.confirmationStatus === 'confirmed' ||
          status?.confirmationStatus === 'finalized') {
        confirmed = true;
        console.log(`✅ Transaction confirmed on-chain (status: ${status.confirmationStatus})`);
        break;
      }

      if (status?.err) {
        throw new Error(`Transaction failed on-chain: ${JSON.stringify(status.err)}`);
      }

      // Wait before next poll
      if (i < maxAttempts - 1) {
        await new Promise(resolve => setTimeout(resolve, pollInterval));
      }
    }

    if (!confirmed) {
      throw new Error("Transaction confirmation timeout after 30 seconds");
    }

    timing.confirm = Math.round(performance.now() - confirmStart);
    console.log(`⏱️  Confirmation time: ${timing.confirm}ms`);

    // Now send to server for verification (transaction already on-chain)
    const verifyStartTime = performance.now();
    timing.totalBeforeSend = Math.round(verifyStartTime - timingStart);
    console.log(`⏱️  Total time before server: ${timing.totalBeforeSend}ms`);

    // NEW x402 header format: on-chain verified (no facilitator needed)
    // Transaction is already broadcasted and confirmed, server verifies on-chain
    const x402Header = {
      x402Version: 1,
      paymentPayload: {
        x402Version: 1,
        scheme: "onchain-verified", // NEW: Direct blockchain verification
        network: "solana",
        payload: {
          signature: signature, // Just signature, not full transaction
          commitment: "confirmed",
        },
      },
      paymentRequirements: {
        scheme: "onchain-verified",
        network: "solana",
        maxAmountRequired: accept.amount,
        resource: `${API_BASE}/api/donate`,
        description: accept.description || "Crypto SuperChat donation",
        mimeType: "application/json",
        payTo: accept.payTo,
        maxTimeoutSeconds: 60,
        asset: accept.asset,
        extra: null,
      },
    };

    show("Verifying on blockchain…");
    const res2 = await fetch(DONATE_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-402-payment": JSON.stringify(x402Header),
      },
      body: JSON.stringify(payload),
    });

    timing.serverVerify = Math.round(performance.now() - verifyStartTime);
    timing.totalFromBlockhash = Math.round(performance.now() - timingStart);

    console.log(`⏱️  Server verification: ${timing.serverVerify}ms`);
    console.log(`⏱️  TOTAL time: ${timing.totalFromBlockhash}ms`);
    console.log("📊 Timing breakdown:");
    console.log(`   Blockhash fetch:     ${timing.blockhash}ms`);
    console.log(`   Transaction build:   ${timing.build}ms`);
    console.log(`   Phantom signing:     ${timing.sign}ms`);
    console.log(`   Broadcast to Solana: ${timing.broadcast}ms`);
    console.log(`   Blockchain confirm:  ${timing.confirm}ms`);
    console.log(`   Server verify:       ${timing.serverVerify}ms`);
    console.log(`   TOTAL:               ${timing.totalFromBlockhash}ms`);

    if (!res2.ok) {
      const t = await res2.text();
      console.error(
        `🔥 Server verification failed after ${timing.serverVerify}ms`,
      );
      console.error(`Transaction signature: ${signature}`);
      console.error(`View on explorer: https://solscan.io/tx/${signature}`);

      throw new Error(`Server verification failed: ${res2.status} ${t}`);
    }

    console.log(`✅ Server verification PASSED in ${timing.serverVerify}ms`);

    // Transaction already broadcasted and confirmed above!
    const done = await res2.json();
    const explorerUrl =
      `https://orb.helius.dev/tx/${signature}?tab=summary&cluster=mainnet-beta`;
    const escapedUrl = escapeAttr(explorerUrl);
    console.log(`🔗 View transaction: ${explorerUrl}`);
    ok(
      `🎉 Payment confirmed on-chain! Submitted for moderation (id ${done.donation_id}).<br><a href="${escapedUrl}" target="_blank" rel="noopener noreferrer">View on Helius Orb</a>`,
    );
    show("");
  } catch (e) {
    console.error(e);
    err(e?.message || String(e));
    show("");
  }
}

// Store privacy score globally
let currentPrivacyScore = null;

// Rate limiting for privacy checks
let lastCheckTime = 0;
const CHECK_COOLDOWN_MS = 5000; // 5 seconds between checks

// Quick wallet privacy check button
const checkWalletBtn = $("checkWalletBtn");
checkWalletBtn?.addEventListener("click", async () => {
  // Client-side rate limiting
  const now = Date.now();
  if (now - lastCheckTime < CHECK_COOLDOWN_MS) {
    const waitSec = Math.ceil(
      (CHECK_COOLDOWN_MS - (now - lastCheckTime)) / 1000,
    );
    show(`Please wait ${waitSec}s before checking again`);
    return;
  }

  const walletInput = $("walletAddressCheck");
  const address = walletInput?.value?.trim();

  if (!address) {
    // If no address provided, use connected Phantom wallet
    const provider = window?.phantom?.solana;
    if (!provider?.isPhantom || !provider.isConnected) {
      err(
        "Please connect your Phantom wallet or paste a wallet address to check",
      );
      return;
    }
    lastCheckTime = now;
    await analyzeWalletPrivacy(provider.publicKey.toString());
    return;
  }

  // Check manually entered address
  lastCheckTime = now;
  await analyzeWalletPrivacy(address);
});

const form = document.querySelector("form");
form.addEventListener("submit", payWithPhantom);
