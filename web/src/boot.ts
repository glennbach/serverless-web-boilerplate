import { fetchEmail } from "./api.ts";
import { signIn, type SignIn } from "./auth.ts";
import { loadConfig } from "./config.ts";

/** The browser pieces boot uses, passed in so tests can replace them. */
export type BootEnv = {
  href: string;
  store: Pick<Storage, "getItem" | "setItem" | "removeItem">;
  now: number;
  fetchFn: typeof fetch;
  replaceUrl(path: string): void;
  assign(url: string): void;
};

/** Loads config, signs in if needed, and returns the email, or null when the page is navigating away. */
export async function boot(env: BootEnv): Promise<string | null> {
  const cfg = await loadConfig(env.fetchFn);
  if (cfg.authMode === "dev") return fetchEmail(cfg.apiBaseUrl, null, env.fetchFn);

  const url = new URL(env.href);
  const isCallback = url.searchParams.has("code") || url.searchParams.has("error");
  let result: SignIn;
  try {
    result = await signIn(cfg, url, env.store, env.now, env.fetchFn);
  } finally {
    // A code works once; never leave it in the address bar to be refreshed.
    if (isCallback) env.replaceUrl("/");
  }
  if ("redirectTo" in result) {
    env.assign(result.redirectTo);
    return null;
  }
  return fetchEmail(cfg.apiBaseUrl, result.idToken, env.fetchFn);
}
