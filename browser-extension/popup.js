const PROVIDERS = {
  "gradescope.com": {
    name: "gradescope",
    // All cookies Gradescope sets for an authenticated session.
    // _gradescope_session is the primary auth token; remember_user_token and
    // signed_token keep the session alive across requests; apt.* are Aptrinsic
    // analytics cookies that Gradescope's JS reads back and can affect responses.
    keys: [
      "_gradescope_session",
      "remember_user_token",
      "signed_token",
      "apt.sid",
      "apt.uid",
    ],
  },
  "piazza.com": {
    name: "piazza",
    // Piazza uses session_id as its primary auth cookie.
    keys: ["session_id"],
  },
};

function detectProvider(url) {
  try {
    const hostname = new URL(url).hostname.replace(/^www\./, "");
    for (const [domain, provider] of Object.entries(PROVIDERS)) {
      if (hostname === domain || hostname.endsWith("." + domain)) {
        return { domain, ...provider };
      }
    }
  } catch (_) {}
  return null;
}

async function loadSavedInputs() {
  const { backendUrl, sessionId } = await chrome.storage.local.get([
    "backendUrl",
    "sessionId",
  ]);
  if (backendUrl) document.getElementById("backend-url").value = backendUrl;
  if (sessionId) document.getElementById("session-id").value = sessionId;
}

async function saveInputs() {
  await chrome.storage.local.set({
    backendUrl: document.getElementById("backend-url").value.trim(),
    sessionId: document.getElementById("session-id").value.trim(),
  });
}

function setStatus(msg, type = "info") {
  const el = document.getElementById("status");
  el.textContent = msg;
  el.className = type;
}

async function init() {
  await loadSavedInputs();

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const provider = tab ? detectProvider(tab.url) : null;

  const badge = document.getElementById("site-badge");
  const btn = document.getElementById("connect-btn");

  if (!provider) {
    badge.textContent = "not supported";
    setStatus("Open a Gradescope or Piazza tab first.", "info");
    return;
  }

  badge.textContent = provider.name;
  btn.textContent = `Connect ${provider.name}`;
  btn.disabled = false;

  btn.addEventListener("click", async () => {
    const backendUrl = document.getElementById("backend-url").value.trim().replace(/\/$/, "");
    const sessionId = document.getElementById("session-id").value.trim();

    if (!sessionId) {
      setStatus("Paste your AskScotty session ID first.", "err");
      return;
    }

    await saveInputs();
    btn.disabled = true;
    setStatus("Fetching cookies…", "info");

    // Fetch all cookies for this provider's domain.
    const allCookies = await chrome.cookies.getAll({ domain: provider.domain });
    const cookieMap = {};
    for (const c of allCookies) {
      // Include every cookie present, not just the known keys — the backend
      // validates and accepts whatever it receives, and more context is better
      // than less when the library's session validation is opaque.
      cookieMap[c.name] = c.value;
    }

    if (Object.keys(cookieMap).length === 0) {
      setStatus("No cookies found — are you logged in?", "err");
      btn.disabled = false;
      return;
    }

    try {
      const resp = await fetch(`${backendUrl}/api/personal/demo/cookies/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Session-ID": sessionId,
        },
        body: JSON.stringify({
          provider: provider.name,
          cookies: cookieMap,
        }),
      });

      if (resp.ok) {
        setStatus(`Connected to ${provider.name}.`, "ok");
      } else {
        const text = await resp.text();
        setStatus(`Error ${resp.status}: ${text.slice(0, 120)}`, "err");
      }
    } catch (err) {
      setStatus(`Network error: ${err.message}`, "err");
    }

    btn.disabled = false;
  });
}

init();
