import { NextResponse } from "next/server";
import fs from "node:fs";
import path from "node:path";
import { storeDir } from "../../../lib/paths";

export const dynamic = "force-dynamic";

/** Public JWKS of the synthetic TEST operator (Ed25519 public key only). */
export async function GET() {
  const file = path.join(storeDir(), "config", "test-operator-jwks.json");
  return new NextResponse(fs.readFileSync(file, "utf8"), {
    headers: {
      "Content-Type": "application/http-message-signatures-directory+json",
      "Cache-Control": "public, max-age=300",
    },
  });
}
