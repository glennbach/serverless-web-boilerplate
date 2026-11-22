// Test-only helpers for the node --test suites. Nothing in the app imports this.

export type Call = { url: string; init?: RequestInit };

/** A fetch stand-in that answers by exact URL from `routes` and records every call. */
export function routedFetch(routes: Record<string, () => Response>): { fetchFn: typeof fetch; calls: Call[] } {
  const calls: Call[] = [];
  const fetchFn = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    const route = routes[url];
    if (!route) throw new Error(`unexpected fetch ${url}`);
    return route();
  }) as typeof fetch;
  return { fetchFn, calls };
}

/** A route that answers with `body` as JSON. */
export const json = (body: unknown, status = 200) => () => new Response(JSON.stringify(body), { status });

/** An in-memory stand-in for sessionStorage. */
export function memoryStore(initial: Record<string, string> = {}) {
  const m = new Map(Object.entries(initial));
  return {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, v),
    removeItem: (k: string) => void m.delete(k),
    has: (k: string) => m.has(k),
  };
}

/** An unsigned JWT with the given payload. Only the SPA's decoding is under test. */
export function jwt(payload: object): string {
  const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "none" })}.${b64(payload)}.sig`;
}

/** 2026-11-22T00:00:00Z, in ms and in seconds. */
export const NOW = Date.UTC(2026, 10, 22);
export const NOW_SEC = NOW / 1000;

export const COGNITO = {
  authMode: "cognito",
  apiBaseUrl: "https://api.example/",
  cognitoDomainUrl: "https://proof.auth.us-west-2.amazoncognito.com",
  clientId: "client123",
} as const;

export const TOKEN_URL = `${COGNITO.cognitoDomainUrl}/oauth2/token`;
