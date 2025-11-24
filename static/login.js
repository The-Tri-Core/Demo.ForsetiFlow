(() => {
  const loginForm = document.getElementById("login-form");
  const verificationForm = document.getElementById("verification-form");
  const statusEl = document.getElementById("login-status");
  const codeInput = document.getElementById("login-code");
  const resendButton = document.getElementById("resend-code");
  const backButton = document.getElementById("back-to-login");
  let pendingToken = null;
  let lastCredentials = null;

  const setStatus = (message, variant = "muted") => {
    if (!statusEl) return;
    statusEl.textContent = message;
    statusEl.classList.toggle("error", variant === "error");
    statusEl.classList.toggle("muted", variant !== "error");
  };

  const showVerificationForm = (hint) => {
    if (!verificationForm || !loginForm) return;
    loginForm.classList.add("hidden");
    verificationForm.classList.remove("hidden");
    setStatus(hint ? `Code sent to ${hint}.` : "Code sent to your phone.");
    codeInput?.focus();
  };

  const showLoginForm = () => {
    pendingToken = null;
    verificationForm?.classList.add("hidden");
    loginForm?.classList.remove("hidden");
    setStatus("");
  };

  async function parseResponse(response) {
    const text = await response.text();
    let json = null;
    if (text) {
      try {
        json = JSON.parse(text);
      } catch (_err) {
        json = null;
      }
    }
    return { response, json, text };
  }

  async function safeFetch(url, options = {}) {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    const response = await fetch(url, { ...options, headers });
    const parsed = await parseResponse(response);
    if (!parsed.response.ok) {
      const message =
        (parsed.json && (parsed.json.message || parsed.json.error)) ||
        parsed.text ||
        parsed.response.statusText ||
        "Request failed";
      throw new Error(message);
    }
    return parsed.json || {};
  }

  const extractCredentials = () => {
    if (!loginForm) return null;
    const data = Object.fromEntries(new FormData(loginForm).entries());
    const identifier = (data.identifier || "").trim();
    const password = data.password || "";
    if (!identifier || !password) {
      setStatus("Username/email and password are required.", "error");
      return null;
    }
    return { identifier, password };
  };

  const requestCode = async (credentials) => {
    try {
      setStatus("Sending verification code…");
      const payload = await safeFetch("/api/auth/start", {
        method: "POST",
        body: JSON.stringify(credentials),
      });
      pendingToken = payload.token;
      lastCredentials = credentials;
      showVerificationForm(payload.phone_hint);
    } catch (err) {
      setStatus(err.message, "error");
    }
  };

  loginForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const credentials = extractCredentials();
    if (!credentials) return;
    requestCode(credentials);
  });

  verificationForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!pendingToken) {
      setStatus("Verification expired. Please sign in again.", "error");
      showLoginForm();
      return;
    }
    const code = (new FormData(verificationForm).get("code") || "").trim();
    if (!code) {
      setStatus("Enter the verification code.", "error");
      return;
    }
    try {
      setStatus("Verifying code…");
      const result = await safeFetch("/api/auth/verify", {
        method: "POST",
        body: JSON.stringify({ token: pendingToken, code }),
      });
      window.location.href = result.redirect || "/app";
    } catch (err) {
      setStatus(err.message, "error");
    }
  });

  resendButton?.addEventListener("click", (event) => {
    event.preventDefault();
    if (!lastCredentials) {
      setStatus("Submit your credentials before requesting another code.", "error");
      return;
    }
    requestCode(lastCredentials);
  });

  backButton?.addEventListener("click", (event) => {
    event.preventDefault();
    showLoginForm();
  });
})();
