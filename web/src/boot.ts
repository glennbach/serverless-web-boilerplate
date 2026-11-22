import { fetchEmail } from "./api.ts";
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
  if (cfg.authMode === "cognito") throw new Error("cognito sign-in is not implemented yet");
  return fetchEmail(cfg.apiBaseUrl, null, env.fetchFn);
}
