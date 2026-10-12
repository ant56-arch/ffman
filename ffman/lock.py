"""Password-protect the website.

GitHub Pages only serves static files, so instead of a login server the page
is encrypted (AES-256-GCM, key from PBKDF2-SHA256 over username + password).
Visitors get a login form; the browser decrypts with WebCrypto. Without the
right username and password the published file is unreadable.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os

from .web import STYLE

ITERATIONS = 600_000


def _salt(username: str) -> bytes:
    # Stable per username, so a remembered device keeps working across rebuilds.
    return hashlib.sha256(b"ffman-site:" + username.strip().lower().encode()).digest()[:16]


def derive_key(username: str, password: str) -> bytes:
    secret = f"{username.strip().lower()}\n{password}".encode()
    return hashlib.pbkdf2_hmac("sha256", secret, _salt(username), ITERATIONS, dklen=32)


def encrypt(html_text: str, username: str, password: str) -> dict:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # only needed when locking

    nonce = os.urandom(12)
    sealed = AESGCM(derive_key(username, password)).encrypt(nonce, html_text.encode(), None)
    return {"iv": base64.b64encode(nonce).decode(), "data": base64.b64encode(sealed).decode(),
            "iterations": ITERATIONS}


LOGIN_STYLE = """
<style>
.login { max-width: 380px; margin: 14vh auto 0; padding-inline: 16px; display: grid; gap: 20px; }
.login h1 { font-size: clamp(40px, 11vw, 64px); line-height: .9; margin: 0; letter-spacing: -.02em; }
.login h1 span { color: var(--turf); -webkit-text-fill-color: var(--turf); }
.login form { background: var(--surface); border: 1px solid var(--line); border-top: 2px solid var(--turf);
  padding: 22px; display: grid; gap: 14px; }
.login label { display: grid; gap: 6px; font: 500 11px/1.2 var(--mono);
  letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
.login input[type=text], .login input[type=password] { font: inherit; font-size: 16px; letter-spacing: 0;
  text-transform: none; padding: 11px 12px; border-radius: 0; border: 1px solid var(--line);
  background: var(--bg); color: var(--ink); }
.login input:focus { outline: 1px solid var(--turf); border-color: var(--turf); }
.login .row { display: flex; align-items: center; gap: 8px; color: var(--ink); }
.login .row input { accent-color: var(--turf); }
.login button { font: 600 15px/1 var(--display); padding: 13px; border-radius: 999px; cursor: pointer;
  border: 0; background: var(--turf); color: #050607; }
.login button:disabled { opacity: .6; cursor: wait; }
.login .err { color: var(--bad); font-size: 14px; margin: 0; min-height: 1.2em; }
.login .note { color: var(--muted); font-size: 13px; margin: 0; }
</style>
"""

LOGIN_SCRIPT = """
<script>
(function () {
  const P = JSON.parse(document.getElementById("payload").textContent);
  const b64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
  const enc = new TextEncoder();
  const form = document.getElementById("login"), err = document.getElementById("err");
  const btn = form.querySelector("button");

  async function deriveKey(user, pass) {
    user = user.trim().toLowerCase();
    const salt = (await crypto.subtle.digest("SHA-256", enc.encode("ffman-site:" + user))).slice(0, 16);
    const base = await crypto.subtle.importKey("raw", enc.encode(user + "\\n" + pass), "PBKDF2", false, ["deriveKey"]);
    return crypto.subtle.deriveKey({ name: "PBKDF2", hash: "SHA-256", salt, iterations: P.iterations },
      base, { name: "AES-GCM", length: 256 }, true, ["decrypt"]);
  }
  async function open(key) {
    const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(P.iv) }, key, b64(P.data));
    const html = new TextDecoder().decode(plain);
    document.open(); document.write(html); document.close();
  }
  async function tryRemembered() {
    let saved = null;
    try { saved = localStorage.getItem("ffman-key"); } catch (e) {}
    if (!saved) return;
    try {
      const key = await crypto.subtle.importKey("raw", b64(saved), "AES-GCM", false, ["decrypt"]);
      await open(key);
    } catch (e) { try { localStorage.removeItem("ffman-key"); } catch (e2) {} }
  }
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    err.textContent = ""; btn.disabled = true; btn.textContent = "Unlocking...";
    try {
      const key = await deriveKey(form.user.value, form.pass.value);
      const raw = new Uint8Array(await crypto.subtle.exportKey("raw", key));
      await open(key);
      if (form.remember.checked) {
        try { localStorage.setItem("ffman-key", btoa(String.fromCharCode(...raw))); } catch (e) {}
      }
    } catch (e) {
      err.textContent = "Wrong username or password.";
      btn.disabled = false; btn.textContent = "Unlock";
    }
  });
  if (!window.crypto || !crypto.subtle) {
    err.textContent = "This browser can't unlock the page. Open it over https in a current browser.";
  } else {
    tryRemembered();
  }
})();
</script>
"""


def login_page(full_html: str, username: str, password: str) -> str:
    """A complete HTML document that unlocks `full_html` with the right login."""
    payload = json.dumps(encrypt(full_html, username, password))
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
        '<meta name="robots" content="noindex, nofollow"></head><body>'
        "<title>ffman Lineups</title>" + STYLE + LOGIN_STYLE +
        '<main class="login"><h1>ffman <span>Lineups</span></h1>'
        '<form id="login" autocomplete="on">'
        '<label for="user">Username<input type="text" id="user" name="user" autocomplete="username" '
        'autocapitalize="none" required></label>'
        '<label for="pass">Password<input type="password" id="pass" name="pass" '
        'autocomplete="current-password" required></label>'
        '<label class="row" for="remember"><input type="checkbox" id="remember" name="remember" checked>'
        "Remember this device</label>"
        '<button type="submit">Unlock</button><p class="err" id="err" role="alert"></p></form>'
        '<p class="note">Private fantasy lineup page.</p></main>'
        f'<script type="application/json" id="payload">{payload}</script>'
        + LOGIN_SCRIPT + "</body></html>"
    )
