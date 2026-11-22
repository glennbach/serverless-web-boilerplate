// Cognito Hosted UI sign-in: authorization-code grant with PKCE, no SDK.
// See ADR 0002, Decision 4.
import type { CognitoConfig } from "./config.ts";

export type KeyValueStore = Pick<Storage, "getItem" | "setItem" | "removeItem">;
export type SignIn = { idToken: string } | { redirectTo: string };

const STATE = "pkce_state";
const VERIFIER = "pkce_verifier";
const SESSION = "session";
/** A token this close to expiry is treated as expired. */
const EXPIRY_MARGIN_MS = 60_000;

function base64url(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** 32 random bytes, base64url without padding (43 characters). */
export function randomString(): string {
  return base64url(crypto.getRandomValues(new Uint8Array(32)));
}

/** The S256 PKCE challenge for a verifier: base64url(SHA-256(verifier)). */
export async function codeChallenge(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64url(new Uint8Array(digest));
}

/** The Hosted UI authorize URL for this client. */
export function authorizeUrl(cfg: CognitoConfig, redirectUri: string, challenge: string, state: string): string {
  const q = new URLSearchParams({
    response_type: "code",
    client_id: cfg.clientId,
    redirect_uri: redirectUri,
    scope: "openid email",
    state,
    code_challenge_method: "S256",
    code_challenge: challenge,
  });
  return `${cfg.cognitoDomainUrl}/oauth2/authorize?${q}`;
}

/**
 * The ID token's `exp` in milliseconds. The token is decoded, not verified;
 * API Gateway verifies it. `expires_in` from the token endpoint describes the
 * access token, whose lifetime Cognito sets separately.
 */
export function idTokenExpiry(idToken: string): number {
  const payload = idToken.split(".")[1];
  if (!payload) throw new Error("The ID token is not a JWT");
  let exp: unknown;
  try {
    exp = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/"))).exp;
  } catch {
    throw new Error("The ID token payload is unreadable");
  }
  if (typeof exp !== "number") throw new Error("The ID token has no exp");
  return exp * 1000;
}

/** Trades an authorization code for the ID token at the token endpoint. */
export async function exchangeCode(
  cfg: CognitoConfig,
  code: string,
  verifier: string,
  redirectUri: string,
  fetchFn: typeof fetch = fetch,
): Promise<{ idToken: string; expiresAt: number }> {
  const res = await fetchFn(`${cfg.cognitoDomainUrl}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      client_id: cfg.clientId,
      code,
      code_verifier: verifier,
      redirect_uri: redirectUri,
    }).toString(),
  });
  if (!res.ok) throw new Error(`Sign-in failed: the token endpoint returned ${res.status}`);
  const idToken = ((await res.json()) as { id_token?: unknown }).id_token;
  if (typeof idToken !== "string") throw new Error("Sign-in failed: no ID token");
  return { idToken, expiresAt: idTokenExpiry(idToken) };
}

function storedSession(store: KeyValueStore, now: number): string | null {
  try {
    const s = JSON.parse(store.getItem(SESSION) ?? "null") as { idToken?: unknown; expiresAt?: unknown } | null;
    if (typeof s?.idToken === "string" && typeof s.expiresAt === "number" && s.expiresAt > now + EXPIRY_MARGIN_MS) {
      return s.idToken;
    }
  } catch {
    // A corrupt session is the same as none.
  }
  return null;
}

/**
 * Returns the ID token, finishing a Hosted UI callback if `url` is one, or the
 * URL to send the browser to for sign-in.
 */
export async function signIn(
  cfg: CognitoConfig,
  url: URL,
  store: KeyValueStore,
  now: number,
  fetchFn: typeof fetch = fetch,
): Promise<SignIn> {
  const redirectUri = `${url.origin}/`;
  const q = url.searchParams;
  const error = q.get("error");
  if (error) throw new Error(`Sign-in failed: ${q.get("error_description") ?? error}`);

  const code = q.get("code");
  if (code) {
    const state = store.getItem(STATE);
    const verifier = store.getItem(VERIFIER);
    // Removed before the exchange, so a failed or replayed callback cannot reuse them.
    store.removeItem(STATE);
    store.removeItem(VERIFIER);
    if (!state || !verifier || q.get("state") !== state) {
      throw new Error("Sign-in failed: this sign-in link is stale or was not started here");
    }
    const session = await exchangeCode(cfg, code, verifier, redirectUri, fetchFn);
    store.setItem(SESSION, JSON.stringify(session));
    return { idToken: session.idToken };
  }

  const idToken = storedSession(store, now);
  if (idToken) return { idToken };

  const state = randomString();
  const verifier = randomString();
  store.setItem(STATE, state);
  store.setItem(VERIFIER, verifier);
  return { redirectTo: authorizeUrl(cfg, redirectUri, await codeChallenge(verifier), state) };
}
