import { NextResponse } from "next/server";
import { readToggles, robotsTxt } from "../../lib/friction";

export const dynamic = "force-dynamic";

export async function GET() {
  return new NextResponse(robotsTxt(readToggles()), {
    headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
  });
}
