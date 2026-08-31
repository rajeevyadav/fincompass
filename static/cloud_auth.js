"use strict";

/*
  FinCompass hosted authentication.
  - Uses Firebase Authentication REST endpoints directly; no third-party JS bundle.
  - Tokens live in this browser only.
  - Same-origin /api/* requests automatically receive the Firebase ID token.
  - The server verifies the token but does not create a FinCompass user database.
*/
(() => {
  const AUTH_STORAGE = "fincompass_cloud_auth_v1";
  const nativeFetch = window.fetch.bind(window);
  let cloudConfig = null;
  let authState = null;
  let refreshPromise = null;

  function loadState() {
    try {
      const raw = window.localStorage.getItem(AUTH_STORAGE);
      const parsed = raw ? JSON.parse(raw) : null;
      if (!parsed || typeof parsed !== "object") return null;
      return parsed;
    } catch (_) { return null; }
  }

  function saveState(value) {
    authState = value || null;
    try {
      if (authState) window.localStorage.setItem(AUTH_STORAGE, JSON.stringify(authState));
      else window.localStorage.removeItem(AUTH_STORAGE);
    } catch (_) {}
  }

  function tokenExpiresSoon(state) {
    if (!state || !state.idToken) return true;
    const expiresAt = Number(state.expiresAt || 0);
    return !expiresAt || Date.now() > expiresAt - 60000;
  }

  async function refreshToken() {
    if (!authState || !authState.refreshToken || !cloudConfig?.firebase?.api_key) return null;
    if (refreshPromise) return refreshPromise;
    refreshPromise = (async () => {
      try {
        const body = new URLSearchParams({
          grant_type: "refresh_token",
          refresh_token: authState.refreshToken,
        });
        const url = `https://securetoken.googleapis.com/v1/token?key=${encodeURIComponent(cloudConfig.firebase.api_key)}`;
        const response = await nativeFetch(url, {
          method: "POST",
          headers: {"Content-Type": "application/x-www-form-urlencoded"},
          body,
        });
        const data = await response.json();
        if (!response.ok || !data.id_token) throw new Error(data?.error?.message || "Session refresh failed");
        saveState({
          ...authState,
          idToken: data.id_token,
          refreshToken: data.refresh_token || authState.refreshToken,
          expiresAt: Date.now() + Number(data.expires_in || 3600) * 1000,
        });
        return authState.idToken;
      } catch (_) {
        saveState(null);
        renderAuth();
        return null;
      } finally {
        refreshPromise = null;
      }
    })();
    return refreshPromise;
  }

  async function currentToken() {
    if (!authState) return null;
    if (tokenExpiresSoon(authState)) return refreshToken();
    return authState.idToken || null;
  }

  async function firebasePassword(endpoint, email, password) {
    const key = cloudConfig?.firebase?.api_key;
    if (!key) throw new Error("Hosted authentication is not configured.");
    const url = `https://identitytoolkit.googleapis.com/v1/accounts:${endpoint}?key=${encodeURIComponent(key)}`;
    const response = await nativeFetch(url, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({email, password, returnSecureToken: true}),
    });
    const data = await response.json();
    if (!response.ok) {
      const raw = String(data?.error?.message || "Authentication failed");
      const friendly = {
        EMAIL_EXISTS: "An account already exists for that email.",
        INVALID_LOGIN_CREDENTIALS: "Email or password is incorrect.",
        INVALID_PASSWORD: "Email or password is incorrect.",
        EMAIL_NOT_FOUND: "Email or password is incorrect.",
        WEAK_PASSWORD: "Use a stronger password (at least 6 characters).",
        INVALID_EMAIL: "Enter a valid email address.",
        TOO_MANY_ATTEMPTS_TRY_LATER: "Too many attempts. Try again later.",
      }[raw] || raw.replaceAll("_", " ").toLowerCase();
      throw new Error(friendly);
    }
    saveState({
      idToken: data.idToken,
      refreshToken: data.refreshToken,
      email: data.email || email,
      localId: data.localId || null,
      expiresAt: Date.now() + Number(data.expiresIn || 3600) * 1000,
    });
    renderAuth();
  }

  function signOut() {
    saveState(null);
    renderAuth();
  }

  function ensureShell() {
    if (document.getElementById("fc-cloud-auth")) return;
    const shell = document.createElement("div");
    shell.id = "fc-cloud-auth";
    shell.innerHTML = `
      <button id="fc-auth-button" class="fc-auth-button" type="button">Sign in</button>
      <div id="fc-auth-backdrop" class="fc-auth-backdrop" hidden>
        <section class="fc-auth-panel" role="dialog" aria-modal="true" aria-labelledby="fc-auth-title">
          <button id="fc-auth-close" class="fc-auth-close" type="button" aria-label="Close">×</button>
          <h2 id="fc-auth-title">Use FinCompass online</h2>
          <p class="fc-auth-privacy">Your research, watchlist, portfolio inputs, forecasts and analytical results are not saved in a FinCompass user database.</p>
          <label>Email<input id="fc-auth-email" type="email" autocomplete="email" required></label>
          <label>Password<input id="fc-auth-password" type="password" autocomplete="current-password" minlength="6" required></label>
          <div id="fc-auth-message" class="fc-auth-message" aria-live="polite"></div>
          <div class="fc-auth-actions">
            <button id="fc-auth-signin" type="button">Sign in</button>
            <button id="fc-auth-signup" type="button" class="secondary">Create free account</button>
          </div>
          <p class="fc-auth-note">Authentication is handled by Firebase. FinCompass does not receive or store your password.</p>
        </section>
      </div>`;
    document.body.appendChild(shell);

    const open = () => { document.getElementById("fc-auth-backdrop").hidden = false; document.getElementById("fc-auth-email")?.focus(); };
    const close = () => { document.getElementById("fc-auth-backdrop").hidden = true; };
    document.getElementById("fc-auth-button").addEventListener("click", () => authState ? signOut() : open());
    document.getElementById("fc-auth-close").addEventListener("click", close);
    document.getElementById("fc-auth-backdrop").addEventListener("click", (e) => { if (e.target.id === "fc-auth-backdrop") close(); });

    async function submit(kind) {
      const email = document.getElementById("fc-auth-email").value.trim();
      const password = document.getElementById("fc-auth-password").value;
      const msg = document.getElementById("fc-auth-message");
      msg.textContent = "";
      try {
        await firebasePassword(kind === "signup" ? "signUp" : "signInWithPassword", email, password);
        close();
      } catch (err) {
        msg.textContent = err?.message || "Authentication failed.";
      }
    }
    document.getElementById("fc-auth-signin").addEventListener("click", () => submit("signin"));
    document.getElementById("fc-auth-signup").addEventListener("click", () => submit("signup"));
  }

  function renderAuth() {
    ensureShell();
    const button = document.getElementById("fc-auth-button");
    if (!button) return;
    button.textContent = authState?.email ? `Sign out · ${authState.email}` : "Sign in";
    button.title = authState?.email ? "Sign out of this browser" : "Sign in or create a free account";
    document.documentElement.dataset.fcAuthenticated = authState ? "true" : "false";

    if (cloudConfig?.auth_mode === "required" && !authState) {
      document.body.classList.add("fc-auth-required");
      const backdrop = document.getElementById("fc-auth-backdrop");
      if (backdrop) backdrop.hidden = false;
    } else {
      document.body.classList.remove("fc-auth-required");
    }
  }

  // Attach current Firebase token to same-origin API calls without changing app.js.
  window.fetch = async function(input, init = {}) {
    const url = typeof input === "string" ? input : input?.url || "";
    let sameOriginApi = false;
    try {
      const resolved = new URL(url, window.location.href);
      sameOriginApi = resolved.origin === window.location.origin && resolved.pathname.startsWith("/api/");
    } catch (_) {}
    if (sameOriginApi && !String(url).includes("/api/cloud/config")) {
      const token = await currentToken();
      if (token) {
        const headers = new Headers(init.headers || (typeof input !== "string" ? input.headers : undefined) || {});
        headers.set("Authorization", `Bearer ${token}`);
        init = {...init, headers};
      }
    }
    const response = await nativeFetch(input, init);
    if (sameOriginApi && response.status === 401 && cloudConfig?.auth_mode === "required") renderAuth();
    return response;
  };

  async function init() {
    authState = loadState();
    try {
      const response = await nativeFetch("/api/cloud/config", {headers: {"Accept": "application/json"}});
      cloudConfig = await response.json();
    } catch (_) {
      cloudConfig = {hosted: false, auth_mode: "off", firebase: {}};
    }
    if (!cloudConfig.hosted || cloudConfig.auth_mode === "off") return;
    if (authState && tokenExpiresSoon(authState)) await refreshToken();
    renderAuth();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, {once: true});
  else init();
})();
