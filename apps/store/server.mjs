// Custom Node server around Next.js: every request (pages, APIs, _next assets) passes through the capture layer.
// Usage: node server.mjs [--dev]   (PORT defaults to 3100; HOST defaults to 127.0.0.1)
import { createServer } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import dotenv from "dotenv";
import next from "next";

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "../..");

// Real environment variables win over .env.
dotenv.config({ path: path.join(repoRoot, ".env") });
process.env.AGENTLENS_REPO_ROOT ||= repoRoot;

const dev = process.argv.includes("--dev");
if (!dev) process.env.NODE_ENV ||= "production";

const port = Number(process.env.PORT || 3100);
const hostname = process.env.HOST || "127.0.0.1";

if (!dev && (!process.env.AGENTLENS_IP_SALT || process.env.AGENTLENS_IP_SALT === "change-me")) {
  console.warn("[agentlens] AGENTLENS_IP_SALT is unset or the default; set it in the repo-root .env for real runs.");
}
if (!process.env.AGENTLENS_IP_SALT) process.env.AGENTLENS_IP_SALT = "change-me";
if (!process.env.AGENTLENS_ADMIN_PASSWORD) process.env.AGENTLENS_ADMIN_PASSWORD = "change-me";

// The capture layer is TypeScript shared with the app; tsx loads it without a build step.
const { tsImport } = await import("tsx/esm/api");
const { capture } = await tsImport("./lib/capture.ts", import.meta.url);

const app = next({ dev, dir: here, hostname, port });
const handle = app.getRequestHandler();
await app.prepare();

const server = createServer((req, res) => {
  capture(req, res, () => handle(req, res));
});

if (dev) {
  const upgrade = app.getUpgradeHandler();
  server.on("upgrade", (req, socket, head) => upgrade(req, socket, head));
}

server.listen(port, hostname, () => {
  console.log(`[agentlens] Desi Threads store (${dev ? "dev" : "prod"}) ready on http://${hostname}:${port}`);
});

const shutdown = () => server.close(() => process.exit(0));
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
