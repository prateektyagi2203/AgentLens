import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const demo = process.env.DEMO_MODE === "1";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  outputFileTracingRoot: path.join(here, "../.."),
  // DEMO_MODE builds a fully static site that reads public/demo/*.json (no backend needed).
  ...(demo ? { output: "export", trailingSlash: true, images: { unoptimized: true } } : {}),
};

export default nextConfig;
