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

/** A non-2xx answer from the API. */
export class ApiError extends Error {
  status: number;
  constructor(status: number) {
    super(`The API returned ${status}`);
    this.status = status;
  }
}

/** Calls GET /api/me and returns the current user's email. Throws ApiError on a non-2xx status. */
export async function fetchEmail(
  apiBaseUrl: string,
  idToken: string | null,
  fetchFn: typeof fetch = fetch,
): Promise<string> {
  const headers: Record<string, string> = idToken ? { Authorization: `Bearer ${idToken}` } : {};
  const res = await fetchFn(`${apiBaseUrl.replace(/\/+$/, "")}/api/me`, { headers });
  if (!res.ok) throw new ApiError(res.status);
  return parseMe(await res.json());
}
