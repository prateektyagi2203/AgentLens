import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const demo = process.env.DEMO_MODE === "1" || process.env.NEXT_PUBLIC_DEMO_MODE === "1";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  outputFileTracingRoot: path.join(here, "../.."),
  // DEMO_MODE (documented name) is exposed to the client as NEXT_PUBLIC_DEMO_MODE.
  env: { NEXT_PUBLIC_DEMO_MODE: demo ? "1" : "" },
  // DEMO_MODE builds a fully static site that reads public/demo/*.json (no backend needed).
  ...(demo ? { output: "export", trailingSlash: true, images: { unoptimized: true } } : {}),
};

export default nextConfig;
