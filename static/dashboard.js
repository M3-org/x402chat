// Import security utilities
import { escapeHtml } from '/security-utils.js';

// Fix secure context issue: redirect 0.0.0.0 to localhost
if (window.location.hostname === "0.0.0.0") {
  console.log(
    "⚠️ Redirecting from 0.0.0.0 to localhost (Phantom requires secure context)",
  );
  const newUrl = window.location.href.replace("0.0.0.0", "localhost");
  window.location.replace(newUrl);
}

class ModerationDashboard {
  constructor() {
    this.ws = null;
    this.status = document.getElementById("status");
    this.donationsTable = document.getElementById("donationsTable");
    this.pendingCount = document.getElementById("pendingCount");
    this.approvedCount = document.getElementById("approvedCount");
    this.rejectedCount = document.getElementById("rejectedCount");

    this.currentTab = "pending";
    this.donations = { pending: [], approved: [], rejected: [] };
    this.sortField = "created_at";
    this.sortOrder = "desc";

    // Check authentication first
    if (!this.checkAuth()) {
      return;
    }

    // TTS initialization
    this.initTTS();

    // Handle URL hash navigation
    this.initHashNavigation();

    // Initialize navigation links
    this.initNavigationLinks();

    this.connect();
    this.loadAllData();
    this.loadOverlayUrl();
  }

  checkAuth() {
    const walletAuth = localStorage.getItem("walletAuth");
    if (!walletAuth) {
      console.warn("⚠️ No authentication - redirecting to home");
      window.location.href = "/";
      return false;
    }
    return true;
  }

  getAuthHeaders() {
    return {
      "Content-Type": "application/json",
    };
  }

  initNavigationLinks() {
    // Set donate link href
    const walletAuth = localStorage.getItem("walletAuth");
    if (walletAuth) {
      const { id } = JSON.parse(walletAuth);
      const donateLink = document.getElementById("donateLink");
      if (donateLink) {
        donateLink.href = `${window.location.origin}/donate/${id}`;
      }
    }

    // Handle signout link with client-side redirect
    const signoutLink = document.getElementById("signoutLink");
    if (signoutLink) {
      signoutLink.addEventListener("click", async (event) => {
        event.preventDefault();
        await fetch("/api/auth/clear");
        window.location.href = "/";
      });
    }
  }

  initHashNavigation() {
    // Listen for hash changes
    window.addEventListener("hashchange", () => {
      this.handleHashChange();
    });

    // Handle initial hash
    this.handleHashChange();
  }

  handleHashChange() {
    const hash = window.location.hash.slice(1); // Remove the '#'
    const validTabs = ["pending", "approved", "rejected", "config"];

    if (hash && validTabs.includes(hash)) {
      this.switchTab(hash);
    }
  }

  initTTS() {
    // Check if speech synthesis is available
    if ("speechSynthesis" in window) {
      this.ttsEnabled = true;
      this.synth = window.speechSynthesis;
      this.voices = [];

      // Load voices (they may load asynchronously)
      this.loadVoices();
      if (speechSynthesis.onvoiceschanged !== undefined) {
        speechSynthesis.onvoiceschanged = () => this.loadVoices();
      }

      // Chrome workaround: voices might not be ready immediately
      // Try loading again after a short delay
      setTimeout(() => {
        if (this.voices.length === 0) {
          console.log("🔄 Retrying voice load...");
          this.loadVoices();
        }
      }, 100);

      console.log("✅ TTS initialized");
    } else {
      this.ttsEnabled = false;
      console.warn("⚠️ Speech Synthesis API not available");
    }
  }

  loadVoices() {
    this.voices = this.synth.getVoices();
    console.log(`📢 Loaded ${this.voices.length} TTS voices`);

    // Populate voice dropdown
    const voiceSelect = document.getElementById("ttsVoice");
    if (voiceSelect) {
      if (this.voices.length > 0) {
        // Save current selection before repopulating
        const currentValue = voiceSelect.value;

        voiceSelect.innerHTML = "";
        this.voices.forEach((voice, index) => {
          const option = document.createElement("option");
          option.value = index;
          option.textContent = `${voice.name} (${voice.lang})`;
          voiceSelect.appendChild(option);
        });

        // Restore previous selection if it was set
        if (currentValue && this.voices[currentValue]) {
          voiceSelect.value = currentValue;
        }
      } else {
        // No voices available (could be Brave browser blocking TTS)
        voiceSelect.innerHTML =
          '<option value="0">No voices available (try Chrome/Firefox)</option>';
      }
    }
  }

  updateTTSValues() {
    // Update displayed values for sliders
    document.getElementById("ttsRateValue").textContent =
      document.getElementById("ttsRate").value;
    document.getElementById("ttsPitchValue").textContent =
      document.getElementById("ttsPitch").value;
    document.getElementById("ttsVolumeValue").textContent =
      document.getElementById("ttsVolume").value;
  }

  testTTS() {
    if (!this.ttsEnabled || !this.synth) {
      alert("TTS not available in your browser");
      return;
    }

    const text = document.getElementById("ttsTestText").value;
    const enabled = document.getElementById("ttsEnabled").checked;

    if (!enabled) {
      alert("TTS is disabled. Enable it to test.");
      return;
    }

    // Cancel any ongoing speech
    this.synth.cancel();

    const utterance = new SpeechSynthesisUtterance(text);

    // Apply settings
    const voiceIndex = parseInt(document.getElementById("ttsVoice").value);
    if (this.voices[voiceIndex]) {
      utterance.voice = this.voices[voiceIndex];
    }

    utterance.rate = parseFloat(document.getElementById("ttsRate").value);
    utterance.pitch = parseFloat(document.getElementById("ttsPitch").value);
    utterance.volume = parseFloat(document.getElementById("ttsVolume").value);

    utterance.onstart = () => {
      console.log("🗣️ TTS started");
    };

    utterance.onend = () => {
      console.log("✅ TTS finished");
    };

    utterance.onerror = (event) => {
      console.error("❌ TTS error:", event.error);
    };

    this.synth.speak(utterance);
  }

  stopTTS() {
    if (this.synth) {
      this.synth.cancel();
    }
  }

  async saveTTSSettings() {
    const button = event.target;
    const originalText = button.textContent;

    try {
      button.disabled = true;
      button.textContent = "💾 Saving...";

      const settings = {
        enabled: document.getElementById("ttsEnabled").checked,
        voice_index: parseInt(document.getElementById("ttsVoice").value),
        rate: parseFloat(document.getElementById("ttsRate").value),
        pitch: parseFloat(document.getElementById("ttsPitch").value),
        volume: parseFloat(document.getElementById("ttsVolume").value),
      };

      console.log("💾 Saving TTS settings:", settings);

      const response = await fetch("/api/config/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || "Failed to save TTS settings");
      }

      const result = await response.json();
      console.log("✅ TTS settings saved:", result);

      // Reload config to update overlay URL
      await this.loadConfig();

      // Show success feedback
      button.textContent = "✅ Saved!";
      setTimeout(() => {
        button.textContent = originalText;
        button.disabled = false;
      }, 2000);
    } catch (error) {
      console.error("❌ Error saving TTS settings:", error);
      button.textContent = "❌ Failed";
      setTimeout(() => {
        button.textContent = originalText;
        button.disabled = false;
      }, 2000);
    }
  }

  connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/dashboard`;
    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      console.log("✅ Dashboard connected");
      this.status.textContent = "Connected";
      this.status.className = "cnc-connected";
    };

    this.ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "new_donation") {
        // Check if donation already exists (deduplication)
        const existingDonation = this.donations.pending.find(
          (d) =>
            (d.id && d.id === data.data.id) ||
            (d.signature && d.signature === data.data.signature),
        );

        if (!existingDonation) {
          this.donations.pending.unshift(data.data);
          this.updateTabCounts();
          if (this.currentTab === "pending") {
            this.renderTable();
          }
        }
      }
    };

    this.ws.onclose = () => {
      console.log("❌ Dashboard disconnected");
      this.status.textContent = "Disconnected";
      this.status.className = "cnc-disconnected";
      setTimeout(() => this.connect(), 3000);
    };
  }

  async loadAllData() {
    await Promise.all([
      this.loadDonationsByStatus("pending"),
      this.loadDonationsByStatus("approved"),
      this.loadDonationsByStatus("rejected"),
    ]);
    this.updateTabCounts();
    this.renderTable();
  }

  async loadDonationsByStatus(status) {
    try {
      let url;
      switch (status) {
        case "pending":
          url = "/api/events/pending";
          break;
        case "approved":
          url = "/api/events/approved";
          break;
        case "rejected":
          url = "/api/events/rejected";
          break;
      }
      const response = await fetch(url, {
        credentials: "include",
      });

      // Handle authentication errors
      if (response.status === 401 || response.status === 403) {
        console.warn("⚠️ Unauthorized - redirecting to home");
        localStorage.removeItem("walletAuth");
        window.location.href = "/";
        return;
      }

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      this.donations[status] = await response.json();
    } catch (error) {
      console.error(`Failed to load ${status} donations:`, error);
      this.donations[status] = [];
    }
  }

  updateTabCounts() {
    this.pendingCount.textContent = this.donations.pending.length;
    this.approvedCount.textContent = this.donations.approved.length;
    this.rejectedCount.textContent = this.donations.rejected.length;
  }

  switchTab(tab) {
    this.currentTab = tab;

    // Update URL hash without triggering hashchange
    if (window.location.hash !== `#${tab}`) {
      window.location.hash = tab;
    }

    // Update tab styling
    document.querySelectorAll('[id^="tab-"]').forEach((t) => {
      t.className = "tab-inactive";
    });
    document.getElementById(`tab-${tab}`).className = "tab-active";

    // Show/hide appropriate view
    if (tab === "config") {
      document.getElementById("donationsView").style.display = "none";
      document.getElementById("configView").style.display = "block";

      // Reload voices first (handles race condition), then load config
      if (this.ttsEnabled) {
        this.loadVoices();
        // Give voices a moment to populate, then load config
        setTimeout(() => this.loadConfig(), 50);
      } else {
        this.loadConfig();
      }
    } else {
      document.getElementById("donationsView").style.display = "block";
      document.getElementById("configView").style.display = "none";
      this.renderTable();
    }
  }

  sortBy(field) {
    if (this.sortField === field) {
      this.sortOrder = this.sortOrder === "asc" ? "desc" : "asc";
    } else {
      this.sortField = field;
      this.sortOrder = "desc";
    }

    // Update sort indicators
    document.querySelectorAll(".sort-button").forEach((btn) => {
      btn.className = "sort-button";
    });

    const currentBtn = document.querySelector(
      `[onclick="dashboard.sortBy('${field}')"]`,
    );
    currentBtn.className = `sort-button sort-${this.sortOrder}`;

    this.renderTable();
  }

  renderTable() {
    if (this.currentTab == "config") {
      return;
    }

    const donations = [...this.donations[this.currentTab]];

    // Sort donations
    donations.sort((a, b) => {
      let aVal = a[this.sortField];
      let bVal = b[this.sortField];

      // Handle different data types
      if (this.sortField === "amount") {
        aVal = parseFloat(aVal) || 0;
        bVal = parseFloat(bVal) || 0;
      } else if (this.sortField === "created_at") {
        aVal = get_unix_time(aVal) || 0;
        bVal = get_unix_time(bVal) || 0;
      } else {
        // String fields (memo, sender, token_symbol)
        aVal = (aVal || "").toString().toLowerCase();
        bVal = (bVal || "").toString().toLowerCase();
      }

      if (this.sortOrder === "asc") {
        return aVal > bVal ? 1 : -1;
      } else {
        return aVal < bVal ? 1 : -1;
      }
    });

    if (donations.length === 0) {
      this.donationsTable.innerHTML = `<tr><td colspan="5" class="muted" style="padding: 1rem;">No ${this.currentTab} donations</td></tr>`;
      return;
    }

    this.donationsTable.innerHTML = donations
      .map(
        (donation) => `
                    <tr class="${
                      donation.status === "playing" ? "donation-playing" : ""
                    }">
                        <td>${this.formatTime(
                          donation.timestamp || donation.created_at,
                        )}</td>
                        <td>${escapeHtml(
                          donation.sender_name ||
                          this.truncateAddress(donation.sender) ||
                          "Unknown"
                        )}</td>
                        <td>$${parseFloat(donation.amount).toFixed(2)}</td>
                        <td>${escapeHtml(
                          donation.message ||
                          donation.memo
                        ) || "<span>No message</span>"}${donation.status === "playing" ? " <span>📺</span>" : ""}</td>
                        <td>
                            ${
                              this.currentTab === "pending"
                                ? `
                                <div>
                                    <button onclick="dashboard.approveDonation('${
                                      donation.signature || donation.id
                                    }')"
                                            class="approve-btn-${
                                              donation.signature || donation.id
                                            }">
                                        ${
                                          donation.status === "playing"
                                            ? "⏹️ Finish"
                                            : "▶️ Play"
                                        }
                                    </button>
                                    <button onclick="dashboard.rejectDonation('${
                                      donation.signature || donation.id
                                    }')"
                                            >
                                        ⏭️ Skip
                                    </button>
                                </div>
                            `
                                : `
                                <button onclick="dashboard.restoreDonation('${
                                  donation.signature || donation.id
                                }')"
                                        >
                                    ↩️ Restore
                                </button>
                            `
                            }
                        </td>
                    </tr>
                `,
      )
      .join("");
  }

  formatTime(timestamp) {
    if (!timestamp) return "N/A";
    // Handle both timestamp (seconds) and created_at (ISO string)
    let date;
    if (typeof timestamp === "string") {
      date = new Date(timestamp);
    } else {
      date = new Date(timestamp * 1000);
    }
    return date.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  truncateAddress(address) {
    if (!address || address.length < 12) return address;
    return `${address.slice(0, 6)}...${address.slice(-4)}`;
  }

  async approveDonation(identifier) {
    console.log("🔵 approveDonation called with identifier:", identifier);

    // Handle both signature-based (memo) and id-based (x402) donations
    // Use == instead of === to handle string vs number comparison
    const donation = this.donations.pending.find(
      (d) => d.signature == identifier || d.id == identifier,
    );

    console.log("Found donation:", donation);

    if (!donation) {
      console.error("❌ Donation not found for identifier:", identifier);
      return;
    }

    if (donation.status === "playing") {
      // Second click: Approve and move to approved tab
      try {
        // Server expects donation_id field
        const requestBody = { donation_id: String(donation.id) };
        const response = await fetch("/api/events/approve", {
          method: "POST",
          headers: this.getAuthHeaders(),
          body: JSON.stringify(requestBody),
          credentials: "include", // Include cookies for session auth
        });

        if (response.ok) {
          // Move from pending to approved
          // Use != instead of !== to handle string vs number comparison
          this.donations.pending = this.donations.pending.filter(
            (d) => d.signature != identifier && d.id != identifier,
          );
          donation.status = "approved";
          this.donations.approved.unshift(donation);
          this.updateTabCounts();
          this.renderTable();
        }
      } catch (error) {
        console.error("Error approving donation:", error);
      }
    } else {
      // First click: Start playing
      try {
        // Check if any donation is already playing
        const alreadyPlaying = this.donations.pending.find(d => d.status === "playing");
        if (alreadyPlaying) {
          alert("Another donation is already playing. Please finish or skip it first.");
          return;
        }

        // Server expects donation_id field
        const requestBody = { donation_id: String(donation.id) };

        console.log("🎮 Play button clicked");
        console.log("Donation object:", donation);
        console.log("Request body:", requestBody);

        const response = await fetch("/api/events/play", {
          method: "POST",
          headers: this.getAuthHeaders(),
          body: JSON.stringify(requestBody),
          credentials: "include", // Include cookies for session auth
        });

        console.log("Response status:", response.status);
        console.log("Response ok:", response.ok);

        if (response.ok) {
          // Mark as playing (client-side state)
          donation.status = "playing";
          this.renderTable();
          console.log("✅ Successfully marked as playing");
        } else {
          const errorText = await response.text();
          console.error(
            "❌ Error starting donation:",
            response.status,
            errorText,
          );
          alert(`Failed to play donation: ${response.status} - ${errorText}`);
        }
      } catch (error) {
        console.error("❌ Exception starting donation:", error);
        alert(`Failed to play donation: ${error.message}`);
      }
    }
  }

  async rejectDonation(identifier) {
    try {
      // Find donation by either signature or id
      // Use == instead of === to handle string vs number comparison
      const donation = this.donations.pending.find(
        (d) => d.signature == identifier || d.id == identifier,
      );
      if (!donation) return;

      // Server expects donation_id field
      const requestBody = { donation_id: String(donation.id) };
      const response = await fetch("/api/events/reject", {
        method: "POST",
        headers: this.getAuthHeaders(),
        body: JSON.stringify(requestBody),
        credentials: "include", // Include cookies for session auth
      });

      if (response.ok) {
        // Move from pending to rejected
        // Use != instead of !== to handle string vs number comparison
        this.donations.pending = this.donations.pending.filter(
          (d) => d.signature != identifier && d.id != identifier,
        );
        donation.status = "rejected";
        this.donations.rejected.unshift(donation);
        this.updateTabCounts();
        this.renderTable();
      }
    } catch (error) {
      console.error("Error rejecting donation:", error);
    }
  }

  async restoreDonation(identifier) {
    try {
      // Find donation in current tab (approved or rejected)
      // Use == instead of === to handle string vs number comparison
      const donation = this.donations[this.currentTab].find(
        (d) => d.signature == identifier || d.id == identifier,
      );
      if (!donation) return;

      // Server expects donation_id field
      const requestBody = { donation_id: String(donation.id) };
      const response = await fetch("/api/events/restore", {
        method: "POST",
        headers: this.getAuthHeaders(),
        body: JSON.stringify(requestBody),
        credentials: "include", // Include cookies for session auth
      });

      if (response.ok) {
        // Remove from current tab
        // Use != instead of !== to handle string vs number comparison
        this.donations[this.currentTab] = this.donations[
          this.currentTab
        ].filter((d) => d.signature != identifier && d.id != identifier);
        // Don't add to pending here - let WebSocket broadcast handle it to avoid duplicates
        this.updateTabCounts();
        this.renderTable();
      }
    } catch (error) {
      console.error("Error restoring donation:", error);
    }
  }

  /* DEAD CODE - No UI elements exist for sync functionality (no syncBtn or syncStatus elements)
   * Candidate for deletion after testing period
   *
  async loadSyncStatus() {
    try {
      const response = await fetch("/api/sync/status");
      const status = await response.json();

      if (status.syncing) {
        this.syncStatus.textContent = "Syncing blockchain...";
        // this.syncStatus.className = "text-sm text-green-400 mt-1";
      } else if (status.last_sync) {
        const timeAgo = this.timeAgo(new Date(status.last_sync));
        this.syncStatus.textContent = `Last sync: ${timeAgo}`;
        // this.syncStatus.className = "text-sm text-gray-400 mt-1";
      } else {
        this.syncStatus.textContent = "Last sync: Never";
        // this.syncStatus.className = "text-sm text-gray-400 mt-1";
      }
    } catch (error) {
      console.error("Failed to load sync status:", error);
    }
  }

  timeAgo(date) {
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return "Just now";
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays}d ago`;
  }

  async syncPendingDonations() {
    const syncBtn = document.getElementById("syncBtn");
    const originalText = syncBtn.innerHTML;

    try {
      syncBtn.innerHTML = "⏳ Syncing...";
      syncBtn.disabled = true;
      this.syncStatus.textContent = "Syncing blockchain...";
      // this.syncStatus.className = "text-sm text-green-400 mt-1";

      const syncResponse = await fetch("/api/sync", {
        method: "POST",
      });
      const syncResult = await syncResponse.json();

      if (!syncResponse.ok) {
        throw new Error(syncResult.detail || "Sync failed");
      }

      syncBtn.innerHTML = `✅ Found ${syncResult.new_donations}`;

      // Reload all data
      await this.loadAllData();

      setTimeout(() => {
        syncBtn.innerHTML = originalText;
        syncBtn.disabled = false;
      }, 3000);
    } catch (error) {
      console.error("Sync failed:", error);
      syncBtn.innerHTML = "❌ Failed";
      this.syncStatus.textContent = `Sync failed: ${error.message}`;
      // this.syncStatus.className = "text-sm text-red-400 mt-1";

      setTimeout(() => {
        syncBtn.innerHTML = originalText;
        syncBtn.disabled = false;
        this.loadSyncStatus();
      }, 3000);
    }
  }
  */

  async exportCSV() {
    this.showCSVWarningModal();
  }

  showCSVWarningModal() {
    const modal = document.getElementById('csvWarningModal');
    const checkbox = document.getElementById('csvWarningCheckbox');
    const confirmBtn = document.getElementById('csvWarningConfirm');
    const cancelBtn = document.getElementById('csvWarningCancel');

    checkbox.checked = false;
    confirmBtn.disabled = true;

    const handleCheckboxChange = () => {
      confirmBtn.disabled = !checkbox.checked;
    };

    const handleCancel = () => {
      modal.style.display = 'none';
      cleanup();
    };

    const handleConfirm = async () => {
      modal.style.display = 'none';
      cleanup();
      await this.performCSVExport();
    };

    const cleanup = () => {
      checkbox.removeEventListener('change', handleCheckboxChange);
      cancelBtn.removeEventListener('click', handleCancel);
      confirmBtn.removeEventListener('click', handleConfirm);
    };

    checkbox.addEventListener('change', handleCheckboxChange);
    cancelBtn.addEventListener('click', handleCancel);
    confirmBtn.addEventListener('click', handleConfirm);

    modal.style.display = 'flex';
  }

  async performCSVExport() {
    try {
      const response = await fetch("/api/export/csv");
      if (!response.ok) {
        throw new Error("Export failed");
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.style.display = "none";
      a.href = url;
      a.download = `donations_${new Date().toISOString().split("T")[0]}.csv`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (error) {
      console.error("CSV export failed:", error);
      alert("Export failed: " + error.message);
    }
  }

  async loadOverlayUrl() {
    try {
      // Get receiver ID from localStorage (wallet auth)
      const walletAuth = localStorage.getItem("walletAuth");

      if (!walletAuth) {
        return;
      }

      const { id: receiver_id } = JSON.parse(walletAuth);

      // Fetch config to get overlay URL
      const response = await fetch(`/api/config?receiver_id=${receiver_id}`);
      if (!response.ok) {
        console.error("Failed to load config for overlay URL");
        return;
      }

      const config = await response.json();

      // Store overlay URL for later use
      this.overlayUrl = config.user.overlay_url;
    } catch (error) {
      console.error("Failed to load overlay URL:", error);
    }
  }

  async loadConfig() {
    try {
      // Get receiver ID from localStorage (wallet auth)
      const walletAuth = localStorage.getItem("walletAuth");

      if (!walletAuth) {
        console.warn("No wallet auth - redirecting to signin");
        window.location.href = "/";
        return;
      }

      const { id: receiver_id } = JSON.parse(walletAuth);

      // Fetch config with receiver_id
      const response = await fetch(`/api/config?receiver_id=${receiver_id}`, {
        credentials: "include",
      });

      // Handle authentication errors
      if (response.status === 401 || response.status === 403) {
        console.warn("⚠️ Unauthorized - redirecting to home");
        localStorage.removeItem("walletAuth");
        window.location.href = "/";
        return;
      }

      if (!response.ok) {
        throw new Error("Failed to load config");
      }

      const config = await response.json();

      // Store overlay URL for later use
      this.overlayUrl = config.user.overlay_url;

      // User info
      document.getElementById("donationUrl").value = config.user.donation_url;

      // Update navigation link to use username if available
      const donateLink = document.getElementById("donateLink");
      if (donateLink) {
        donateLink.href = config.user.donation_url;
      }

      // Statistics
      document.getElementById("statTotalDonations").textContent =
        config.statistics.total_donations;
      document.getElementById("statPending").textContent =
        config.statistics.pending;
      document.getElementById("statApproved").textContent =
        config.statistics.approved;
      document.getElementById("statRejected").textContent =
        config.statistics.rejected;
      document.getElementById("statTotalAmount").textContent =
        "$" + config.statistics.total_amount.toFixed(2);

      // Settings
      document.getElementById("configNetwork").textContent =
        config.x402_settings.network;
      document.getElementById("configUsername").value =
        config.user.username || "";
      document.getElementById("configPayTo").value =
        config.x402_settings.pay_to_address || "";
      document.getElementById("configDefaultAmount").value =
        config.x402_settings.default_donation_amount;
      document.getElementById("configMaxName").textContent =
        config.content_limits.max_sender_name_length;
      document.getElementById("configMaxMessage").textContent =
        config.content_limits.max_message_length;

      // TTS Settings
      if (config.tts_settings) {
        document.getElementById("ttsEnabled").checked =
          config.tts_settings.enabled;
        document.getElementById("ttsVoice").value =
          config.tts_settings.voice_index;
        document.getElementById("ttsRate").value = config.tts_settings.rate;
        document.getElementById("ttsPitch").value = config.tts_settings.pitch;
        document.getElementById("ttsVolume").value = config.tts_settings.volume;

        // Update displayed values
        this.updateTTSValues();
      }

      // Setup save button handler for username
      const saveUsernameBtn = document.getElementById("saveUsernameBtn");
      saveUsernameBtn.onclick = async () => {
        const newUsername = document.getElementById("configUsername").value.trim();
        try {
          saveUsernameBtn.textContent = "Saving...";
          saveUsernameBtn.disabled = true;

          const response = await fetch("/api/config/username", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username: newUsername }),
          });

          if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || `Failed to save: ${response.status}`);
          }

          const result = await response.json();
          saveUsernameBtn.textContent = "✅ Saved!";
          setTimeout(() => {
            saveUsernameBtn.textContent = "Save";
            saveUsernameBtn.disabled = false;
          }, 2000);

          // Reload config to show updated donation URL
          await this.loadConfig();
        } catch (error) {
          console.error("Failed to save username:", error);
          alert("Failed to save username: " + error.message);
          saveUsernameBtn.textContent = "Save";
          saveUsernameBtn.disabled = false;
        }
      };

      // Setup save button handler for pay-to address
      const saveBtn = document.getElementById("savePayToBtn");
      saveBtn.onclick = async () => {
        const newAddress = document.getElementById("configPayTo").value.trim();
        try {
          saveBtn.textContent = "Saving...";
          saveBtn.disabled = true;

          const response = await fetch("/api/config/pay-to-address", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ pay_to_address: newAddress }),
          });

          if (!response.ok) {
            throw new Error(`Failed to save: ${response.status}`);
          }

          const result = await response.json();
          saveBtn.textContent = "✅ Saved!";
          setTimeout(() => {
            saveBtn.textContent = "Save";
            saveBtn.disabled = false;
          }, 2000);

          // Reload config to show updated value
          await this.loadConfig();
        } catch (error) {
          console.error("Failed to save pay-to address:", error);
          alert("Failed to save: " + error.message);
          saveBtn.textContent = "Save";
          saveBtn.disabled = false;
        }
      };

      // Setup save button handler for default donation amount
      const saveDefaultAmountBtn = document.getElementById("saveDefaultAmountBtn");
      saveDefaultAmountBtn.onclick = async () => {
        const newAmount = document.getElementById("configDefaultAmount").value.trim();
        try {
          saveDefaultAmountBtn.textContent = "Saving...";
          saveDefaultAmountBtn.disabled = true;

          const response = await fetch("/api/config/default-donation-amount", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ default_donation_amount: newAmount }),
          });

          if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || `Failed to save: ${response.status}`);
          }

          const result = await response.json();
          saveDefaultAmountBtn.textContent = "✅ Saved!";
          setTimeout(() => {
            saveDefaultAmountBtn.textContent = "Save";
            saveDefaultAmountBtn.disabled = false;
          }, 2000);

          // Reload config to show updated value
          await this.loadConfig();
        } catch (error) {
          console.error("Failed to save default amount:", error);
          alert("Failed to save default amount: " + error.message);
          saveDefaultAmountBtn.textContent = "Save";
          saveDefaultAmountBtn.disabled = false;
        }
      };
    } catch (error) {
      console.error("Failed to load config:", error);
      alert("Failed to load configuration: " + error.message);
    }
  }

  copyToClipboard(elementId) {
    const element = document.getElementById(elementId);
    element.select();
    element.setSelectionRange(0, 99999); // For mobile devices

    try {
      document.execCommand("copy");
      // Visual feedback
      const button = event.target;
      const originalText = button.textContent;
      button.textContent = "✅ Copied!";
      setTimeout(() => {
        button.textContent = originalText;
      }, 2000);
    } catch (err) {
      console.error("Failed to copy:", err);
      alert("Failed to copy URL. Please copy manually.");
    }
  }

  showObsModal() {
    // Populate the overlay URL in the modal
    const urlInput = document.getElementById("obsOverlayUrl");
    if (urlInput && this.overlayUrl) {
      urlInput.value = this.overlayUrl;
    }

    // Show the modal
    const modal = document.getElementById("obsSetupModal");
    if (modal) {
      modal.style.display = "flex";
    }
  }

  closeObsModal() {
    const modal = document.getElementById("obsSetupModal");
    if (modal) {
      modal.style.display = "none";
    }
  }

  copyOverlayUrl() {
    const urlInput = document.getElementById("obsOverlayUrl");
    if (urlInput) {
      urlInput.select();
      document.execCommand("copy");
      alert("✅ Overlay URL copied to clipboard!");
    }
  }

  openOverlayWindow() {
    // Open overlay in a popup window sized for OBS
    const width = 800;
    const height = 600;
    const left = (screen.width - width) / 2;
    const top = (screen.height - height) / 2;

    // Use overlay URL with TTS settings if available, otherwise fallback to /overlay
    const overlayUrl = this.overlayUrl || "/overlay";

    window.open(
      overlayUrl,
      "OverlayWindow",
      `width=${width},height=${height},left=${left},top=${top},toolbar=no,menubar=no,location=no,status=no`
    );
  }
}

// Global dashboard instance
let dashboard;
window.addEventListener("DOMContentLoaded", () => {
  dashboard = new ModerationDashboard();
  window.dashboard = dashboard;  // Explicit global exposure for onclick handlers
});

function get_unix_time(dateStr) {
  const date = new Date(dateStr);
  const timestamp = Math.floor(date.getTime() / 1000);
  return timestamp;
}
