import { NextResponse } from "next/server";
import { ADMIN_COOKIE, adminEnabled, adminToken, passwordMatches } from "../../../../lib/admin";
import { apiError, readJson, str } from "../../../../lib/api";

export async function POST(req: Request) {
  if (!adminEnabled()) return apiError(req, 404, "NOT_FOUND");
  const body = await readJson(req);
  if (!passwordMatches(str(body.password))) return apiError(req, 401, "ADMIN_AUTH");
  const res = NextResponse.json({ ok: true }, { headers: { "Cache-Control": "no-store" } });
  res.cookies.set(ADMIN_COOKIE, adminToken(), { httpOnly: true, sameSite: "strict", path: "/" });
  return res;
}
