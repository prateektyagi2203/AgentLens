import crypto from "node:crypto";
import { parseCookies } from "./client";

export const ADMIN_COOKIE = "dt_admin";

/** Admin is disabled in public demo mode. */
export const adminEnabled = () => process.env.DEMO_MODE !== "1";

const password = () => process.env.AGENTLENS_ADMIN_PASSWORD || "change-me";

export function adminToken(): string {
  const salt = process.env.AGENTLENS_IP_SALT || "change-me";
  return crypto.createHash("sha256").update(`admin|${password()}|${salt}`).digest("hex");
}

function safeEqual(a: string, b: string): boolean {
  const ha = crypto.createHash("sha256").update(a).digest();
  const hb = crypto.createHash("sha256").update(b).digest();
  return crypto.timingSafeEqual(ha, hb);
}

export function passwordMatches(candidate: string): boolean {
  return safeEqual(candidate, password());
}

/** Authorised by the admin cookie (browser) or the x-admin-password header (scripts, tests). */
export function isAdminRequest(headers: { get(name: string): string | null }): boolean {
  if (!adminEnabled()) return false;
  const header = headers.get("x-admin-password");
  if (header && passwordMatches(header)) return true;
  const cookie = parseCookies(headers.get("cookie"))[ADMIN_COOKIE];
  return !!cookie && safeEqual(cookie, adminToken());
}
