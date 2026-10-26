// Cognito hosted UI login with the authorization-code flow and PKCE. No
// library: the hosted UI does the forms, this file does the redirect, the
// code exchange and token refresh. Tokens live in sessionStorage only.
const cfg = () => window.TLG_ACADEMY || {};
const KEY = "tlg_academy_auth";
const PKCE = "tlg_academy_pkce";

const b64url = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

async function pkce() {
  const bytes = crypto.getRandomValues(new Uint8Array(48));
  const verifier = b64url(bytes);
  const challenge = b64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  const state = b64url(crypto.getRandomValues(new Uint8Array(16)));
  sessionStorage.setItem(PKCE, JSON.stringify({ verifier, state, returnTo: location.hash || "#/" }));
  return { challenge, state };
}

export const redirectUri = () => `${location.origin}/`;
export const configured = () => Boolean(cfg().authDomain && cfg().clientId);

export async function login(path = "login") {
  if (!configured()) { alert("The academy login is not configured yet."); return; }
  const { challenge, state } = await pkce();
  const q = new URLSearchParams({
    client_id: cfg().clientId, response_type: "code", scope: "openid email profile",
    redirect_uri: redirectUri(), state, code_challenge: challenge, code_challenge_method: "S256",
  });
  location.assign(`https://${cfg().authDomain}/${path}?${q}`);
}
export const signup = () => login("signup");

export function logout() {
  sessionStorage.removeItem(KEY);
  if (!configured()) { location.hash = "#/"; return; }
  const q = new URLSearchParams({ client_id: cfg().clientId, logout_uri: redirectUri() });
  location.assign(`https://${cfg().authDomain}/logout?${q}`);
}

function save(tokens) {
  const t = { ...tokens, expires_at: Date.now() + (tokens.expires_in || 3600) * 1000 - 30000 };
  if (!t.refresh_token && current()?.refresh_token) t.refresh_token = current().refresh_token;
  sessionStorage.setItem(KEY, JSON.stringify(t));
  return t;
}
function current() {
  try { return JSON.parse(sessionStorage.getItem(KEY) || "null"); } catch { return null; }
}

async function tokenRequest(params) {
  const res = await fetch(`https://${cfg().authDomain}/oauth2/token`, {
    method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: cfg().clientId, ...params }),
  });
  if (!res.ok) throw new Error(`token request failed (${res.status})`);
  return res.json();
}

/** Call once on page load. Completes a login if the URL carries a code. Returns the hash to go to. */
export async function completeLogin() {
  const url = new URL(location.href);
  const code = url.searchParams.get("code");
  if (!code) return null;
  const stash = JSON.parse(sessionStorage.getItem(PKCE) || "{}");
  sessionStorage.removeItem(PKCE);
  if (!stash.verifier || url.searchParams.get("state") !== stash.state) {
    history.replaceState(null, "", "/"); throw new Error("login state mismatch; please try again");
  }
  const tokens = await tokenRequest({ grant_type: "authorization_code", code, redirect_uri: redirectUri(), code_verifier: stash.verifier });
  save(tokens);
  history.replaceState(null, "", "/" + (stash.returnTo || "#/"));
  return stash.returnTo || "#/";
}

/** A valid id token, refreshing when it is about to expire; null when logged out. */
export async function idToken() {
  const t = current();
  if (!t?.id_token) return null;
  if (Date.now() < t.expires_at) return t.id_token;
  if (!t.refresh_token) { sessionStorage.removeItem(KEY); return null; }
  try {
    return save(await tokenRequest({ grant_type: "refresh_token", refresh_token: t.refresh_token })).id_token;
  } catch {
    sessionStorage.removeItem(KEY); return null;
  }
}

export function claims() {
  const t = current();
  if (!t?.id_token) return null;
  try {
    const payload = t.id_token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(decodeURIComponent(escape(atob(payload))));
  } catch { return null; }
}
export const loggedIn = () => Boolean(current()?.id_token);
