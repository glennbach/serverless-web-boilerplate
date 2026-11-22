/** Local: no sign-in, and the API is on this origin through the Vite proxy. */
export type DevConfig = { authMode: "dev"; apiBaseUrl: string };

/** Deployed: Cognito Hosted UI sign-in, and the API on API Gateway. */
export type CognitoConfig = {
  authMode: "cognito";
  apiBaseUrl: string;
  /** The Hosted UI's https origin, e.g. https://proof-dev.auth.us-west-2.amazoncognito.com */
  cognitoDomainUrl: string;
  clientId: string;
};

export type Config = DevConfig | CognitoConfig;

function str(raw: Record<string, unknown>, key: string, nonEmpty: boolean): string {
  const v = raw[key];
  if (typeof v !== "string" || (nonEmpty && v === "")) {
    throw new Error(`config.json: ${key} must be a${nonEmpty ? " nonempty" : ""} string`);
  }
  return v;
}

/** Checks the shape of config.json. Throws an Error naming the bad field. */
export function parseConfig(raw: unknown): Config {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    throw new Error("config.json: not a JSON object");
  }
  const r = raw as Record<string, unknown>;
  const apiBaseUrl = str(r, "apiBaseUrl", false);
  if (r.authMode === "dev") return { authMode: "dev", apiBaseUrl };
  if (r.authMode !== "cognito") throw new Error('config.json: authMode must be "dev" or "cognito"');
  const cognitoDomainUrl = str(r, "cognitoDomainUrl", true);
  if (!cognitoDomainUrl.startsWith("https://")) {
    throw new Error("config.json: cognitoDomainUrl must start with https://");
  }
  return { authMode: "cognito", apiBaseUrl, cognitoDomainUrl, clientId: str(r, "clientId", true) };
}

/** Fetches and checks /config.json from this origin. */
export async function loadConfig(fetchFn: typeof fetch = fetch): Promise<Config> {
  const res = await fetchFn("/config.json", { cache: "no-cache" });
  if (!res.ok) throw new Error(`config.json returned ${res.status}`);
  return parseConfig(await res.json());
}
