import { NextResponse } from "next/server";
import { setRequestMeta } from "../../../lib/state";

function beacon(req: Request) {
  setRequestMeta(req.headers.get("x-agentlens-request-id"), { eventType: "beacon" });
  return new NextResponse(null, { status: 204, headers: { "Cache-Control": "no-store" } });
}

export const POST = beacon;
export const GET = beacon;
