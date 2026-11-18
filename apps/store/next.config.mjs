import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Compression is off so bytes_out in the access log is the exact body size sent.
  compress: false,
  outputFileTracingRoot: path.join(here, "../.."),
};

export default nextConfig;
