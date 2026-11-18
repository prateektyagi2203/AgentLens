// Builds the static public-demo site (`out/`): next build with DEMO_MODE=1, cross-platform (no cross-env needed).
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";

const next = createRequire(import.meta.url).resolve("next/dist/bin/next");
const res = spawnSync(process.execPath, [next, "build"], { stdio: "inherit", env: { ...process.env, DEMO_MODE: "1" } });
process.exit(res.status ?? 1);
