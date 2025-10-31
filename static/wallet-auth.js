/**
 * Wallet-Based Authentication Module
 *
 * Provides stateless, cryptographic authentication using Solana wallet signatures.
 * No cookies, no sessions - just wallet signatures!
 * Uses modern Sign-In with Solana (SIWS) API when available.
 */

import bs58 from "https://esm.sh/bs58@5.0.0";

/**
 * Sign a message with the connected Phantom wallet
 * @param {string} message - Message to sign
 * @returns {Promise<string>} - Base58-encoded signature
 */
export async function signMessage(message) {
  if (!window.solana || !window.solana.isPhantom) {
    throw new Error("Phantom wallet not found");
  }

  if (!window.solana.isConnected) {
    await window.solana.connect();
  }

  const encoded = new TextEncoder().encode(message);
  const { signature } = await window.solana.signMessage(encoded, "utf8");
  return bs58.encode(signature);
}

/**
 * Create authentication payload for API requests
 * @param {string} purpose - Purpose of the authentication (e.g., "dashboard", "moderation")
 * @returns {Promise<Object>} - Auth object with publicKey, message, signature, timestamp
 */
export async function createWalletAuth(purpose = "api-access") {
  if (!window.solana || !window.solana.isPhantom) {
    throw new Error("Phantom wallet not found");
  }

  if (!window.solana.isConnected) {
    await window.solana.connect();
  }

  const publicKey = window.solana.publicKey.toString();
  const timestamp = Math.floor(Date.now() / 1000);
  const message = `${purpose}:${timestamp}`;

  const signature = await signMessage(message);

  return {
    publicKey,
    message,
    signature,
    timestamp,
  };
}

/**
 * Make an authenticated API call with wallet signature
 * @param {string} endpoint - API endpoint
 * @param {Object} data - Request data
 * @param {string} purpose - Purpose for the auth signature
 * @returns {Promise<Response>} - Fetch response
 */
export async function authenticatedFetch(
  endpoint,
  data = {},
  purpose = "api-access",
) {
  const auth = await createWalletAuth(purpose);

  return fetch(endpoint, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      ...data,
      auth,
    }),
  });
}

/**
 * Verify wallet authentication and get receiver ID
 * @returns {Promise<Object>} - {id, publicKey}
 */
export async function verifyWalletAuth() {
  const auth = await createWalletAuth("dashboard-access");

  const response = await fetch("/api/auth/wallet-verify", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(auth),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Authentication failed");
  }

  return response.json();
}

/**
 * Connect wallet and verify authentication
 * @returns {Promise<{id: string, publicKey: string}>}
 */
export async function connectAndVerify() {
  const provider = window?.phantom?.solana;

  if (!provider || !provider.isPhantom) {
    throw new Error("Phantom wallet not found. Please install Phantom.");
  }

  console.log("Phantom detected. Using Sign-In with Solana (SIWS)...");

  // Check if signIn is available (newer Phantom versions)
  if (typeof provider.signIn === "function") {
    console.log("✅ Using modern signIn() API");

    try {
      const timestamp = Math.floor(Date.now() / 1000);

      const signInData = {
        domain: window.location.host,
        statement: "Sign in to x402 Chat with your Solana wallet",
        version: "1",
        nonce: timestamp.toString(),
        chainId: "mainnet",
        issuedAt: new Date().toISOString(),
      };

      console.log("Calling provider.signIn()...");
      const output = await provider.signIn(signInData);

      console.log("✅ Sign-In complete!", output);

      // Extract data from SIWS output
      // Output format: {address: PublicKey, signedMessage: Uint8Array, signature: Uint8Array}
      const publicKey = output.address.toString();
      const signedMessageStr = new TextDecoder().decode(output.signedMessage);
      const signatureBase58 = bs58.encode(output.signature);

      console.log("Decoded:", { publicKey, signedMessageStr });

      // Verify the signature with our backend
      const auth = {
        publicKey,
        message: signedMessageStr,
        signature: signatureBase58,
        timestamp,
      };

      const response = await fetch("/api/auth/wallet-verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(auth),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || "Authentication failed");
      }

      const result = await response.json();
      console.log("✅ Wallet authenticated:", result);
      return result;
    } catch (error) {
      console.error("❌ signIn failed:", error);
      throw new Error(`Sign-In failed: ${error.message}`);
    }
  } else {
    // Fallback to old connect() method
    console.log("⚠️ signIn() not available, using legacy connect()");

    try {
      await provider.connect({ onlyIfTrusted: false });
      console.log("✅ Connected via legacy method");

      const result = await verifyWalletAuth();
      return result;
    } catch (error) {
      console.error("❌ Connection failed:", error);
      throw new Error(`Failed to connect: ${error.message}`);
    }
  }
}
