// Generates the deterministic, synthetic TEST operator keypair (Ed25519) used by signed synthetic agents.
// Output: config/test-operator-jwks.json (public JWKS) and config/test-operator.private.pem (PKCS8).
// This key protects nothing: it only signs fake agent traffic for the identification tests.
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const configDir = path.join(here, "..", "config");

const seed = crypto.createHash("sha256").update("agentlens-test-operator-v1").digest();
const pkcs8Prefix = Buffer.from("302e020100300506032b657004220420", "hex");
const privateKey = crypto.createPrivateKey({
  key: Buffer.concat([pkcs8Prefix, seed]),
  format: "der",
  type: "pkcs8",
});
const publicJwk = crypto.createPublicKey(privateKey).export({ format: "jwk" });

// RFC 7638 thumbprint over the required members, in lexicographic order.
const thumbprint = crypto
  .createHash("sha256")
  .update(JSON.stringify({ crv: publicJwk.crv, kty: publicJwk.kty, x: publicJwk.x }))
  .digest("base64url");

const jwks = { keys: [{ kty: publicJwk.kty, crv: publicJwk.crv, x: publicJwk.x, kid: thumbprint }] };

fs.mkdirSync(configDir, { recursive: true });
fs.writeFileSync(path.join(configDir, "test-operator-jwks.json"), JSON.stringify(jwks, null, 2) + "\n");
fs.writeFileSync(
  path.join(configDir, "test-operator.private.pem"),
  privateKey.export({ format: "pem", type: "pkcs8" }),
);
console.log(`test operator key written, kid=${thumbprint}`);
