(() => {
  const form = document.getElementById("setup-form");
  const statusEl = document.getElementById("setup-status");
  const setStatus = (message, variant = "muted") => {
    if (!statusEl) return;
    statusEl.textContent = message;
    statusEl.classList.toggle("error", variant === "error");
    statusEl.classList.toggle("muted", variant !== "error");
  };
  async function parseResponse(response) {
    const text = await response.text();
    let json = null;
    if (text) {
      try { json = JSON.parse(text); } catch {}
    }
    return { response, json, text };
  }
  async function safeFetch(url, options = {}) {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    const response = await fetch(url, { ...options, headers });
    const parsed = await parseResponse(response);
    if (!parsed.response.ok) {
      const message = (parsed.json && (parsed.json.message || parsed.json.error)) || parsed.text || parsed.response.statusText || "Request failed";
      throw new Error(message);
    }
    return parsed.json || {};
  }
  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form).entries());
    const totp_code = (data.totp_code || "").trim();
    if (!totp_code) { setStatus("Authenticator code is required.", "error"); return; }
    try {
      setStatus("Completing setup...");
      const result = await safeFetch("/api/auth/setup-first", { method: "POST", body: JSON.stringify({ totp_code }) });
      window.location.href = result.redirect || "/app";
    } catch (err) {
      setStatus(err.message, "error");
    }
  });
})();
