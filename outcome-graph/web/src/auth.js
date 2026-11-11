// Sign-in, shared by both pages. Firebase Auth with Google sign-in: Identity Platform in production,
// the Firebase Auth emulator locally (compose.yaml). The server verifies the ID token on every call.
// Accounts are optional; with no database configured the page runs signed-out only.
import { initializeApp } from "firebase/app";
import {
  initializeAuth, connectAuthEmulator, GoogleAuthProvider, signInWithPopup, signInWithRedirect, signOut as fbSignOut,
  onAuthStateChanged, signInWithEmailAndPassword, browserLocalPersistence, inMemoryPersistence,
  browserPopupRedirectResolver,
} from "firebase/auth";

const S = { cfg: null, auth: null, user: null, me: null, subs: [] };
let readyResolve;
// Resolves with the signed-in user (or null) once Firebase reports, or after 2.5 s regardless, so
// the page never waits on sign-in to show content. A late report re-renders through onMe.
export const ready = new Promise((r) => { readyResolve = r; setTimeout(() => r(S.me), 2500); });

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

export async function initAuth() {
  try { S.cfg = await (await fetch("/api/config")).json(); } catch { S.cfg = { accounts: false, agent: false }; }
  if (!S.cfg.accounts) { readyResolve(null); return S.cfg; }
  try {
    const app = initializeApp(S.cfg.firebase);
    // localStorage, not IndexedDB: IndexedDB can hang in some browsers and private windows
    S.auth = initializeAuth(app, { persistence: [browserLocalPersistence, inMemoryPersistence], popupRedirectResolver: browserPopupRedirectResolver });
  } catch (e) {
    console.warn("[oversight] sign-in unavailable", e);
    readyResolve(null);
    return S.cfg;
  }
  if (S.cfg.authEmulator) {
    connectAuthEmulator(S.auth, S.cfg.authEmulator, { disableWarnings: true });
    // local testing only: the emulator accepts any email and password
    window.__oversightSignIn = (email, pw) => signInWithEmailAndPassword(S.auth, email, pw);
  }
  onAuthStateChanged(S.auth, async (u) => {
    S.user = u;
    S.me = u ? await refreshMe() : null;
    readyResolve(S.me);
    S.subs.forEach((f) => f(S.me));
  });
  return S.cfg;
}

export const config = () => S.cfg;
export const me = () => S.me;
export const signedIn = () => !!S.me;
export function onMe(f) { S.subs.push(f); }

// A random id this browser keeps, so signed-out limits are per browser, not per network: a whole
// campus shares one address.
export function clientId() {
  try {
    let id = localStorage.getItem("oversight-client");
    if (!id) { id = crypto.randomUUID?.() || String(Math.random()).slice(2); localStorage.setItem("oversight-client", id); }
    return id;
  } catch { return ""; }
}
export async function authFetch(url, opts = {}) {
  const headers = { ...(opts.headers || {}), "X-Oversight-Client": clientId() };
  if (S.user) headers.Authorization = "Bearer " + (await S.user.getIdToken());
  return fetch(url, { ...opts, headers });
}

export async function refreshMe() {
  if (!S.user) return null;
  try {
    const r = await authFetch("/api/me");
    S.me = r.ok ? await r.json() : null;
  } catch { S.me = null; }
  return S.me;
}

export async function saveProfile(patch) {
  const r = await authFetch("/api/me", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) });
  if (r.ok) { S.me = await r.json(); S.subs.forEach((f) => f(S.me)); }
  return S.me;
}

function google() {
  const p = new GoogleAuthProvider();
  p.setCustomParameters({ prompt: "select_account" });  // people with two Google accounts get to pick
  return p;
}
export async function signIn() {
  if (!S.auth) { toast("Sign-in isn't available right now."); return; }
  document.querySelectorAll(".acct-in, .pitch-in").forEach((b) => { b.disabled = true; b.dataset.label ||= b.innerHTML; b.textContent = "Signing in…"; });
  const restore = () => document.querySelectorAll(".acct-in, .pitch-in").forEach((b) => { b.disabled = false; if (b.dataset.label) b.innerHTML = b.dataset.label; });
  try {
    // Locally, the emulator's sign-in page as a popup tends to open behind Chrome or in another
    // full-screen Space, so go there by redirect instead. Production keeps the popup.
    if (S.cfg.authEmulator) { await signInWithRedirect(S.auth, google()); return; }
    await signInWithPopup(S.auth, google());
  } catch (e) {
    const code = e?.code || "";
    if (code === "auth/popup-blocked" || code === "auth/operation-not-supported-in-this-environment") {
      await signInWithRedirect(S.auth, google());  // popups blocked: go by redirect
    } else if (code !== "auth/popup-closed-by-user" && code !== "auth/cancelled-popup-request") {
      toast(code === "auth/network-request-failed" ? "Can't reach the sign-in service." : `Sign-in failed: ${code || e.message}`);
      console.warn("[oversight] sign-in", e);
    }
  } finally { restore(); }
}
export function toast(msg, ok = false) {
  let t = document.getElementById("acct-toast");
  if (!t) { t = document.createElement("div"); t.id = "acct-toast"; document.body.appendChild(t); }
  t.textContent = msg;
  t.classList.toggle("ok", ok);
  t.classList.add("on");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove("on"), 5000);
}
export async function signOut() { if (S.auth) { await fbSignOut(S.auth); toast("Signed out", true); } }

export const ORG_TYPES = {
  utility: "Water utility", advocacy: "Advocacy group", trade: "Trade association", state: "State or local agency",
  industry: "Company", law_firm: "Law firm", academic: "Researcher", press: "Press", resident: "Resident", other: "Other",
};

// The account button: "Sign in" when signed out, an initial with a menu when signed in.
export function accountWidget(el, { compact = false } = {}) {
  if (!S.cfg?.accounts) { el.remove(); return; }
  const render = (m) => {
    if (!m) {
      el.innerHTML = `<button class="acct-in" type="button">${compact ? "Sign in" : `<svg viewBox="0 0 24 24" width="14" height="14"><path fill="currentColor" d="M21.6 12.2c0-.7-.1-1.4-.2-2H12v3.8h5.4a4.6 4.6 0 0 1-2 3v2.5h3.2c1.9-1.7 3-4.3 3-7.3z"/><path fill="currentColor" opacity=".75" d="M12 22c2.7 0 5-.9 6.6-2.4l-3.2-2.5c-.9.6-2 1-3.4 1-2.6 0-4.8-1.8-5.6-4.1H3.1v2.6A10 10 0 0 0 12 22z"/><path fill="currentColor" opacity=".55" d="M6.4 14c-.2-.6-.3-1.3-.3-2s.1-1.4.3-2V7.4H3.1a10 10 0 0 0 0 9.2L6.4 14z"/><path fill="currentColor" opacity=".9" d="M12 6c1.5 0 2.8.5 3.8 1.5l2.9-2.9A10 10 0 0 0 3.1 7.4L6.4 10C7.2 7.7 9.4 6 12 6z"/></svg> Sign in with Google`}</button>`;
      el.querySelector("button").addEventListener("click", () => signIn());
      return;
    }
    const u = m.user;
    const initial = (u.name || u.email || "?").trim()[0].toUpperCase();
    el.innerHTML = `<button class="acct-me" type="button" title="${esc(u.email)}">${esc(initial)}</button>
      <div class="acct-menu">
        <div class="acct-who"><b>${esc(u.name || u.email)}</b><span>${esc(u.email)}</span>${u.org_type ? `<span>${esc(ORG_TYPES[u.org_type])}${u.org_name ? " at " + esc(u.org_name) : ""} · <a href="/#yours" class="acct-edit">Edit</a></span>` : ""}</div>
        <a href="/#yours">Your chats and drafts</a>
        <div class="acct-left">${m.left.ask} questions and ${m.left.coach} comment checks left today</div>
        <button type="button" class="acct-out">Sign out</button>
      </div>`;
    const btn = el.querySelector(".acct-me");
    btn.addEventListener("click", (e) => { e.stopPropagation(); el.classList.toggle("open"); });
    document.addEventListener("click", (e) => { if (!el.contains(e.target)) el.classList.remove("open"); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && el.classList.contains("open")) { el.classList.remove("open"); btn.focus(); } });
    el.querySelector(".acct-out").addEventListener("click", () => signOut());
  };
  render(S.me);
  onMe(render);
}
