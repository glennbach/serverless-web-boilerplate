/**
 * Checks the GET /api/me body at runtime. TypeScript cannot see what Go
 * sends, so this is the SPA's half of the contract (ADR 0002, Decision 4).
 */
export function parseMe(body: unknown): string {
  const email = (body as { email?: unknown } | null)?.email;
  if (typeof email !== "string" || email === "") {
    throw new Error("The API response has no email");
  }
  return email;
}

/** Calls GET /api/me and returns the current user's email. */
export async function fetchEmail(
  apiBaseUrl: string,
  idToken: string | null,
  fetchFn: typeof fetch = fetch,
): Promise<string> {
  const headers: Record<string, string> = idToken ? { Authorization: `Bearer ${idToken}` } : {};
  const res = await fetchFn(`${apiBaseUrl.replace(/\/+$/, "")}/api/me`, { headers });
  if (!res.ok) throw new Error(`The API returned ${res.status}`);
  return parseMe(await res.json());
}
