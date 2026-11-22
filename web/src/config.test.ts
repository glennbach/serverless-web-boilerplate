import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { parseConfig } from "./config.ts";

const cognito = {
  authMode: "cognito",
  apiBaseUrl: "https://api.example",
  cognitoDomainUrl: "https://proof.auth.us-west-2.amazoncognito.com",
  clientId: "client123",
};

test("parses dev", () => {
  assert.deepEqual(parseConfig({ authMode: "dev", apiBaseUrl: "" }), { authMode: "dev", apiBaseUrl: "" });
});

test("parses cognito", () => {
  assert.deepEqual(parseConfig({ ...cognito }), cognito);
});

test("rejects bad configs", () => {
  const bad = [
    null,
    "x",
    {},
    { authMode: "prod", apiBaseUrl: "" },
    { authMode: "dev" },
    { ...cognito, clientId: undefined },
    { ...cognito, clientId: "" },
    { ...cognito, cognitoDomainUrl: "proof.auth.us-west-2.amazoncognito.com" },
  ];
  for (const raw of bad) assert.throws(() => parseConfig(raw), Error, JSON.stringify(raw));
});

test("committed public/config.json is a valid dev config", () => {
  const raw = JSON.parse(readFileSync(new URL("../public/config.json", import.meta.url), "utf8"));
  assert.equal(parseConfig(raw).authMode, "dev");
});
