import { connectAndVerify } from "/wallet-auth.js";

// Fix secure context issue: redirect 0.0.0.0 to localhost
if (window.location.hostname === "0.0.0.0") {
  console.log(
    "⚠️ Redirecting from 0.0.0.0 to localhost (Phantom requires secure context)",
  );
  const newUrl = window.location.href.replace("0.0.0.0", "localhost");
  window.location.replace(newUrl);
}

function go_to_dashboard(id) {
  console.log(`going to dashboard of: ${id}`);
  window.location.href = "/dashboard";
}

async function signin() {
  console.log("🔐 Starting wallet-based authentication (no cookies!)");

  try {
    // New wallet-based auth - no sessions, no cookies!
    const { id, publicKey, needsConfig } = await connectAndVerify();

    console.log(`✅ Authenticated wallet: ${publicKey.slice(0, 8)}...`);
    console.log(`✅ Receiver ID: ${id}`);

    // Store for dashboard use (persists across sessions)
    localStorage.setItem("walletAuth", JSON.stringify({ id, publicKey }));

    // Always redirect to config page on sign-in
    console.log("✅ Redirecting to config page");
    window.location.href = "/dashboard#config";
  } catch (error) {
    console.error("❌ Authentication failed:", error);
    alert(
      `Authentication failed: ${error.message}\n\nPlease make sure:\n1. Phantom wallet is installed and unlocked\n2. You have registered this wallet before`,
    );
  }
}

// Add event listener to sign-in button
document.querySelector("#signin").addEventListener("click", signin);

// Add shine effect and tilt to demo cards
function initDemoCardShine() {
  // Skip on mobile/touch devices
  if (window.matchMedia("(max-width: 640px)").matches || "ontouchstart" in window) {
    return;
  }

  const cards = document.querySelectorAll(".demo-preview");

  cards.forEach((card) => {
    card.addEventListener("mousemove", (e) => {
      const rect = card.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      const centerX = rect.width / 2;
      const centerY = rect.height / 2;

      // Calculate tilt angles (max ±8 degrees)
      const rotateY = ((x - centerX) / centerX) * 8;
      const rotateX = ((centerY - y) / centerY) * 8;

      // Calculate gradient angle based on mouse position
      const angle = Math.atan2(y - centerY, x - centerX) * (180 / Math.PI);

      // Apply tilt transform (no lift, subtle scale)
      card.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale(1.01)`;

      // Apply shine properties
      card.style.setProperty(
        "--shine-angle",
        `${angle + 90}deg`,
      );
      card.style.setProperty("--shine-x", `${x}px`);
      card.style.setProperty("--shine-y", `${y}px`);
    });

    card.addEventListener("mouseleave", () => {
      card.style.transform = "";
      card.style.removeProperty("--shine-angle");
      card.style.removeProperty("--shine-x");
      card.style.removeProperty("--shine-y");
    });
  });
}

// Initialize shine effect when DOM is ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initDemoCardShine);
} else {
  initDemoCardShine();
}
