import fs from "node:fs";
import path from "node:path";
import type { Product } from "./catalog";
import { isAssetPath } from "./logger";
import { frictionFile } from "./paths";
import { registry } from "./state";
import {
  DEFAULT_TOGGLES,
  FRICTION_IDS,
  allOff,
  type FrictionId,
  type Toggles,
} from "./friction-meta";

export { DEFAULT_TOGGLES, FRICTION_IDS, type FrictionId, type Toggles };

export const DEV_OTP = "123456";

/* ------------------------------------------------------------------ storage */

export interface FrictionFile {
  toggles: Toggles;
  updated_at: string;
}

function normalise(raw: unknown): Toggles {
  const out = allOff();
  const src = (raw as { toggles?: Record<string, unknown> } | null)?.toggles ?? {};
  for (const id of FRICTION_IDS) out[id] = src[id] === true;
  return out;
}

/** Cheap read: one stat() per call, re-parse only when the file changed (admin edits apply without restart). */
export function readToggles(): Toggles {
  const file = frictionFile();
  const reg = registry();
  let stamp: string;
  try {
    const st = fs.statSync(file);
    stamp = `${file}|${st.mtimeMs}|${st.size}`;
  } catch {
    return { ...DEFAULT_TOGGLES };
  }
  if (reg.frictionCache && reg.frictionCache.key === stamp) return reg.frictionCache.toggles as Toggles;
  try {
    const toggles = normalise(JSON.parse(fs.readFileSync(file, "utf8")));
    reg.frictionCache = { key: stamp, toggles };
    return toggles;
  } catch {
    // Half-written file: keep serving the last good state.
    return (reg.frictionCache?.toggles as Toggles | undefined) ?? { ...DEFAULT_TOGGLES };
  }
}

export function writeToggles(patch: Partial<Record<FrictionId, boolean>>): { toggles: Toggles; changed: FrictionId[] } {
  const before = readToggles();
  const next = { ...before };
  const changed: FrictionId[] = [];
  for (const id of FRICTION_IDS) {
    if (typeof patch[id] === "boolean" && patch[id] !== before[id]) {
      next[id] = patch[id] as boolean;
      changed.push(id);
    }
  }
  const file = frictionFile();
  const body: FrictionFile = { toggles: next, updated_at: new Date().toISOString() };
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(body, null, 2) + "\n");
  registry().frictionCache = null;
  return { toggles: next, changed };
}

/* ------------------------------------------------------------------ F01 bot wall */

export const AGENT_UA_TOKENS = [
  "ChatGPT-User", "ChatGPT-Agent", "OAI-SearchBot", "GPTBot", "Claude-User", "Claude-SearchBot", "ClaudeBot",
  "Claude-Web", "anthropic-ai", "Perplexity-User", "PerplexityBot", "Google-Agent", "Googlebot", "Applebot",
  "Amazonbot", "meta-externalagent", "meta-externalfetcher", "CCBot", "Bytespider", "DuckAssistBot",
  "MistralAI-User", "TestSignedAgent", "python-httpx", "python-requests", "HeadlessChrome-Agent",
];

/** UAs never blocked by the bot wall (our own replay agent). */
export const ALLOWED_UA_TOKENS = ["AgentLens-Replay"];

export function botWallBlocks(t: Toggles, ua: string | null | undefined): boolean {
  if (!t.F01) return false;
  const u = ua ?? "";
  const lower = u.toLowerCase();
  if (ALLOWED_UA_TOKENS.some((tok) => lower.includes(tok.toLowerCase()))) return false;
  if (!u.includes("Mozilla")) return true;
  return AGENT_UA_TOKENS.some((tok) => lower.includes(tok.toLowerCase()));
}

export function botChallengeHtml(): string {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Checking your browser</title></head>
<body style="font-family:sans-serif;text-align:center;padding:4rem">
<h1>Checking your browser before accessing Desi Threads</h1>
<p>This process is automatic. Please enable JavaScript and cookies and complete the challenge to continue.</p>
<p style="color:#888">Reference: 403</p>
<p style="color:#b00;margin-top:2rem">TEST STORE: no real orders</p></body></html>`;
}

/* ------------------------------------------------------------------ F12 rate limit */

export class RateLimiter {
  private hits = new Map<string, number[]>();
  constructor(
    private limit = 20,
    private windowMs = 60_000,
  ) {}

  /** Records the request unless the client is already over the limit. */
  hit(key: string, now: number): { limited: boolean; retryAfterSec: number } {
    const arr = (this.hits.get(key) ?? []).filter((t) => now - t < this.windowMs);
    if (arr.length >= this.limit) {
      this.hits.set(key, arr);
      return { limited: true, retryAfterSec: Math.max(1, Math.ceil((arr[0] + this.windowMs - now) / 1000)) };
    }
    arr.push(now);
    this.hits.set(key, arr);
    if (this.hits.size > 10_000) this.prune(now);
    return { limited: false, retryAfterSec: 0 };
  }

  private prune(now: number) {
    for (const [k, v] of this.hits) if (!v.some((t) => now - t < this.windowMs)) this.hits.delete(k);
  }
}

/* ------------------------------------------------------------------ F13 slow pages */

export const isPdpPath = (p: string) => /^\/p\/[^/]+\/?$/.test(p);

export function pdpDelayMs(t: Toggles, pathname: string, rng: () => number = Math.random): number {
  if (!t.F13 || !isPdpPath(pathname)) return 0;
  return 6000 + Math.floor(rng() * 3001);
}

/* ------------------------------------------------------------------ server-level gate (F01, F12, F13) */

export interface GateInput {
  path: string;
  ua: string | null;
  rateKey: string;
  now: number;
  toggles: Toggles;
}

export type GateDecision =
  | { action: "allow"; delayMs: number }
  | {
      action: "block";
      status: number;
      errorCode: "BOT_CHALLENGE" | "RATE_LIMITED";
      contentType: string;
      body: string;
      headers: Record<string, string>;
    };

const BOT_WALL_EXEMPT = /^\/(admin|api\/admin|robots\.txt|\.well-known\/)/;

/** Paths excluded from the bot wall: assets and operator/policy endpoints. */
export function botWallExempt(pathname: string): boolean {
  return isAssetPath(pathname) || BOT_WALL_EXEMPT.test(pathname);
}

/** Paths excluded from rate limiting and latency: the above plus the beacon. */
export function gateExempt(pathname: string): boolean {
  return botWallExempt(pathname) || pathname === "/api/beacon";
}

export function decideGate(
  input: GateInput,
  limiter: RateLimiter,
  rng: () => number = Math.random,
): GateDecision {
  const { path: p, toggles: t } = input;
  if (!botWallExempt(p) && botWallBlocks(t, input.ua)) {
    return {
      action: "block",
      status: 403,
      errorCode: "BOT_CHALLENGE",
      contentType: "text/html; charset=utf-8",
      body: botChallengeHtml(),
      headers: {},
    };
  }
  if (gateExempt(p)) return { action: "allow", delayMs: 0 };
  if (t.F12) {
    const r = limiter.hit(input.rateKey, input.now);
    if (r.limited) {
      return {
        action: "block",
        status: 429,
        errorCode: "RATE_LIMITED",
        contentType: "application/json",
        body: JSON.stringify({ error_code: "RATE_LIMITED", message: "Too many requests" }),
        headers: { "Retry-After": String(r.retryAfterSec) },
      };
    }
  }
  return { action: "allow", delayMs: pdpDelayMs(t, p, rng) };
}

/* ------------------------------------------------------------------ F14 robots */

export const ROBOTS_AGENT_TOKENS = [
  "GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "Claude-User", "Claude-SearchBot",
  "PerplexityBot", "Perplexity-User", "Google-Extended", "Applebot-Extended", "CCBot", "Bytespider",
  "meta-externalagent", "TestSignedAgent",
];

export function robotsTxt(t: Toggles, origin?: string): string {
  const lines = ["User-agent: *", "Allow: /", "Disallow: /admin", ""];
  if (t.F14) {
    for (const tok of ROBOTS_AGENT_TOKENS) {
      lines.push(`User-agent: ${tok}`, "Disallow: /p/", "Disallow: /checkout", "");
    }
  }
  if (origin) lines.push(`Sitemap: ${origin}/sitemap.xml`);
  return lines.join("\n").trimEnd() + "\n";
}

/* ------------------------------------------------------------------ cart / checkout / PDP decisions */

export interface CartGuardState {
  pincodeOk: boolean;
  otpVerified: boolean;
}

export type CartRejection =
  | { status: 409; error_code: "PINCODE_REQUIRED" }
  | { status: 401; error_code: "AUTH_REQUIRED"; redirect: string };

/** F05 (pincode wall) is checked before F06 (OTP before cart). */
export function cartGuard(t: Toggles, s: CartGuardState): CartRejection | null {
  if (t.F05 && !s.pincodeOk) return { status: 409, error_code: "PINCODE_REQUIRED" };
  if (t.F06 && !s.otpVerified) return { status: 401, error_code: "AUTH_REQUIRED", redirect: "/login" };
  return null;
}

/** F11: the two flagged products get a different cart price than the PDP price. */
export function cartUnitPrice(t: Toggles, p: Pick<Product, "price" | "price_mismatch" | "cart_price">): number {
  return t.F11 && p.price_mismatch && p.cart_price != null ? p.cart_price : p.price;
}

const STRICT_PHONE = /^\+91 \d{5} \d{5}$/;
const LENIENT_CHARS = /^[+\d\s\-()]+$/;

/** F10 strict: exactly "+91 XXXXX XXXXX". Otherwise any plausible Indian mobile number is accepted. */
export function phoneValid(t: Toggles, phone: unknown): boolean {
  if (typeof phone !== "string") return false;
  if (t.F10) return STRICT_PHONE.test(phone);
  if (!LENIENT_CHARS.test(phone)) return false;
  return /^(91)?[6-9]\d{9}$/.test(phone.replace(/\D/g, ""));
}

export function captchaRequired(t: Toggles, solved: boolean): boolean {
  return t.F02 && !solved;
}

export function codOtpRequired(t: Toggles, method: string, verified: boolean): boolean {
  return t.F15 && method === "COD" && !verified;
}

export interface OosPolicy {
  /** HTTP status for an out-of-stock selection. */
  status: 409 | 200;
  alternatives: boolean;
}

/** F16 on: a bare 409. Off: availability info plus in-stock alternatives. */
export function oosPolicy(t: Toggles): OosPolicy {
  return t.F16 ? { status: 409, alternatives: false } : { status: 200, alternatives: true };
}

export interface PdpRender {
  priceInHtml: boolean;
  jsonLd: "none" | "basic" | "full";
}

export function pdpRender(t: Toggles): PdpRender {
  return { priceInHtml: !t.F03, jsonLd: t.F04 ? "none" : t.F03 ? "basic" : "full" };
}

export function sizeGuideMode(t: Toggles): "image-only" | "table-and-image" {
  return t.F09 ? "image-only" : "table-and-image";
}

export interface Overlays {
  pincodeModal: boolean;
  appInterstitial: boolean;
  spinWheel: boolean;
  /** Milliseconds before the interstitial close button appears. */
  closeDelayMs: number;
  captcha: boolean;
}

export function overlays(t: Toggles): Overlays {
  return { pincodeModal: t.F05, appInterstitial: t.F07, spinWheel: t.F08, closeDelayMs: 3000, captcha: t.F02 };
}
