import type {
  BlockerId,
  EvidenceItem,
  FiredRule,
  SessionDetail,
  SessionRequest,
  SessionRow,
  SignatureStatus,
  StageId,
} from "../types";
import { BLOCKER_BY_ID, BLOCKERS, UNITS, type UnitDef } from "./catalog";
import { CHANGE_DAY, DAYS, applies } from "./engine";
import { idFrom, mulberry32, pick, weightedPick } from "./prng";

const SLUGS = [
  "white-court-sneaker",
  "indigo-kurta-set",
  "cotton-linen-shirt",
  "block-print-dupatta",
  "leather-kolhapuri-sandal",
];
const PINCODES = ["560001", "400001", "110001", "600001", "500001", "411001"];

interface Req {
  method: string;
  path: string;
  status: number;
  dur: number;
  type?: string | null;
  err?: string | null;
  stage?: StageId | null;
  asset?: boolean;
  gap?: number;
}

function baseSteps(slug: string, pin: string, upTo: number, browsing: boolean, rnd: () => number): Req[] {
  const out: Req[] = [];
  const dur = (lo: number, hi: number) => Math.round(lo + rnd() * (hi - lo));
  if (upTo >= 1) {
    if (rnd() < 0.6) out.push({ method: "GET", path: "/", status: 200, dur: dur(90, 260), type: "home", stage: "S1" });
    out.push({
      method: "GET", path: rnd() < 0.5 ? "/c/sneakers" : "/search?q=" + slug.split("-")[0], status: 200,
      dur: dur(120, 340), type: "listing", stage: out.length ? null : "S1",
    });
  }
  if (upTo >= 2) {
    out.push({ method: "GET", path: `/p/${slug}`, status: 200, dur: dur(140, 420), type: "pdp", stage: "S2" });
    if (browsing) {
      out.push({ method: "GET", path: "/static/app.4f2c.js", status: 200, dur: dur(30, 90), asset: true, type: "asset" });
      out.push({ method: "POST", path: "/beacon", status: 204, dur: dur(10, 40), asset: true, type: "beacon" });
    }
  }
  if (upTo >= 3) {
    out.push({ method: "GET", path: `/api/products/${slug}/variants?size=9`, status: 200, dur: dur(60, 180), type: "api", stage: "S3" });
  }
  if (upTo >= 4) {
    out.push({ method: "GET", path: `/api/serviceability?pincode=${pin}`, status: 200, dur: dur(70, 210), type: "api", stage: "S4" });
  }
  if (upTo >= 5) out.push({ method: "POST", path: "/api/cart", status: 201, dur: dur(110, 280), type: "api", stage: "S5" });
  if (upTo >= 6) out.push({ method: "GET", path: "/checkout", status: 200, dur: dur(130, 330), type: "checkout", stage: "S6" });
  if (upTo >= 7) out.push({ method: "POST", path: "/api/checkout", status: 201, dur: dur(220, 520), type: "api", stage: "S7" });
  if (upTo >= 8) {
    out.push({
      method: "GET", path: `/order/confirmed/ORD-${Math.floor(10000 + rnd() * 89999)}`, status: 200,
      dur: dur(110, 260), type: "order", stage: "S8",
    });
  }
  return out;
}

interface Journey {
  reqs: Req[];
  maxStage: StageId;
  evidence: EvidenceItem[] | ((ids: string[]) => EvidenceItem[]);
  summary: string;
}

function journeyFor(
  blocker: BlockerId | "converted",
  slug: string,
  pin: string,
  unit: UnitDef | null,
  rnd: () => number,
): Journey {
  const browsing = unit?.agent_class !== "user_fetcher";
  const cap = (n: number) => (browsing ? n : Math.min(n, 3));
  const dur = (lo: number, hi: number) => Math.round(lo + rnd() * (hi - lo));
  if (blocker === "converted") {
    return { reqs: baseSteps(slug, pin, 8, true, rnd), maxStage: "S8", evidence: [], summary: "" };
  }
  const upTo = (n: number) => baseSteps(slug, pin, cap(n), browsing, rnd);
  const withTail = (n: number, tail: Req[], evidence: Journey["evidence"], summary: string): Journey => ({
    reqs: [...upTo(n), ...tail],
    maxStage: `S${Math.min(cap(n), 8)}` as StageId,
    evidence,
    summary,
  });
  const reqEv = (summary: string) => (ids: string[]): EvidenceItem[] => [
    { type: "request", request_id: ids[ids.length - 1], summary },
  ];
  switch (blocker) {
    case "B01":
      return withTail(1, [{ method: "GET", path: `/p/${slug}`, status: 403, dur: dur(40, 110), err: "WAF_CHALLENGE", type: "challenge" }],
        reqEv(`GET /p/${slug} → 403 (challenge page) · agent: ${unit?.agent_name ?? "agent"} (${unit?.tier ?? "declared"})`), "403 challenge");
    case "B02":
      return withTail(5, [{ method: "GET", path: "/checkout", status: 200, dur: dur(130, 330), type: "captcha_interstitial" }, { method: "GET", path: "/captcha/challenge", status: 200, dur: dur(80, 200), type: "captcha", err: "CAPTCHA_REQUIRED" }],
        reqEv("GET /checkout → 200 · GET /captcha/challenge → 200 · no solution submitted"), "captcha");
    case "B03":
      return {
        reqs: [...baseSteps(slug, pin, 1, false, rnd), { method: "GET", path: `/p/${slug}`, status: 200, dur: dur(180, 380), type: "pdp", err: "PRICE_NOT_IN_HTML" }],
        maxStage: "S1",
        evidence: [
          { type: "site_check", check: "pdp_ssr_price", result: "missing" },
          { type: "request", request_id: "", summary: `GET /p/${slug} → 200 · fetched and ended (no JavaScript executed)` },
        ],
        summary: "price missing in server HTML",
      };
    case "B04":
      return withTail(1, [{ method: "GET", path: `/p/${slug}`, status: 200, dur: dur(180, 380), type: "pdp", err: "JSONLD_INCOMPLETE" }],
        [{ type: "site_check", check: "jsonld_product", result: "warn" }], "structured data incomplete");
    case "B05": {
      const n = rnd() < 0.35 ? 3 : 2;
      const tail: Req[] = Array.from({ length: n }, (_, i) => ({
        method: "POST", path: "/api/cart", status: 409, dur: dur(90, 200), err: "PINCODE_REQUIRED", type: "api", gap: i === 0 ? 1200 : 2000,
      }));
      return withTail(4, tail, reqEv(`POST /api/cart → 409 PINCODE_REQUIRED (×${n}) · session ended ${Math.round(2 + rnd() * 6)} s later`), "pincode required");
    }
    case "B06":
      return withTail(4, [
        { method: "POST", path: "/api/cart", status: 401, dur: dur(60, 150), err: "UNAUTHENTICATED", type: "api" },
        { method: "GET", path: "/login", status: 200, dur: dur(100, 240), type: "login" },
        { method: "POST", path: "/api/otp/send", status: 200, dur: dur(300, 700), type: "api", err: "OTP_SENT_NO_VERIFY" },
      ], reqEv("POST /api/cart → 401 → GET /login → POST /api/otp/send · no verify · ended"), "login wall");
    case "B07":
      return {
        reqs: [...baseSteps(slug, pin, 1, true, rnd), { method: "GET", path: `/p/${slug}`, status: 200, dur: dur(150, 330), type: "pdp", err: "OVERLAY_NO_INTERACTION" },
          { method: "POST", path: "/beacon", status: 204, dur: dur(10, 40), asset: true, type: "beacon" }],
        maxStage: "S1",
        evidence: reqEv(`GET /p/${slug} → 200 · beacon seen · no further request for ${Math.round(30 + rnd() * 40)} s`),
        summary: "overlay without interaction",
      };
    case "B08":
      return withTail(2, [{ method: "GET", path: `/api/products/${slug}/variants?size=9`, status: 409, dur: dur(60, 140), err: "VARIANT_OUT_OF_STOCK", type: "api" }],
        reqEv(`GET /api/products/${slug}/variants?size=9 → 409 VARIANT_OUT_OF_STOCK · ended`), "out of stock");
    case "B09":
      return withTail(2, [{ method: "GET", path: `/size-guide/${slug}.png`, status: 200, dur: dur(80, 220), type: "size_guide_image", err: "SIZE_GUIDE_IMAGE" }],
        [{ type: "site_check", check: "size_guide_format", result: "fail" }], "image-only size guide");
    case "B10": {
      const n = 3;
      const tail: Req[] = Array.from({ length: n }, (_, i) => ({
        method: "POST", path: "/api/checkout", status: 422, dur: dur(120, 260), err: "PHONE_FORMAT", type: "api", gap: i === 0 ? 1500 : 2500,
      }));
      return withTail(6, tail, reqEv(`POST /api/checkout → 422 PHONE_FORMAT (×${n})`), "phone validation");
    }
    case "B11":
      return withTail(6, [
        { method: "POST", path: "/api/checkout", status: 202, dur: dur(200, 420), err: "COD_OTP_REQUIRED", type: "api" },
        { method: "GET", path: "/api/payment/cod-otp", status: 200, dur: dur(100, 260), type: "api" },
      ], reqEv("POST /api/checkout → 202 COD_OTP_REQUIRED · no OTP verify · ended"), "COD OTP");
    case "B12":
      return withTail(1, [{ method: "GET", path: `/p/${slug}`, status: 429, dur: dur(10, 40), err: "RATE_LIMITED", type: "pdp" }],
        reqEv(`GET /p/${slug} → 429 Retry-After: 60 · ended`), "rate limited");
    case "B13":
      return withTail(1, [{ method: "GET", path: "/c/sneakers", status: 504, dur: 7400, err: "TIMEOUT", type: "listing" }],
        reqEv("GET /c/sneakers → 504 after 7.4 s · ended"), "timeout");
    case "B14":
      return {
        reqs: [{ method: "GET", path: "/robots.txt", status: 200, dur: dur(10, 40), type: "robots", err: "ROBOTS_DISALLOW" }],
        maxStage: "S1",
        evidence: reqEv(`GET /robots.txt → 200 · User-agent: ${unit?.agent_name ?? "agent"} Disallow: /`),
        summary: "robots disallow",
      };
    case "B15":
      return withTail(5, [{ method: "GET", path: "/cart", status: 200, dur: dur(100, 240), type: "cart", err: "PRICE_MISMATCH" }],
        reqEv("PDP ₹2,199 · cart ₹2,499 · session ended"), "price mismatch");
    case "B16":
      return {
        reqs: [...baseSteps(slug, pin, 1, browsing, rnd), { method: "GET", path: `/p/${slug}-old`, status: 404, dur: dur(30, 90), err: "NOT_FOUND", type: "pdp" }],
        maxStage: "S1",
        evidence: reqEv(`GET /p/${slug}-old → 404 · ended`),
        summary: "404",
      };
    default:
      return withTail(3, [], [], "no rule fired");
  }
}

export interface SessionSeed {
  row: SessionRow;
  detail: SessionDetail;
}

const SEEDS: SessionSeed[] = [];

function buildSession(day: string, rnd: () => number): SessionSeed {
  const phase = day < CHANGE_DAY ? "before" : "after";
  const isHuman = rnd() < 0.17;
  const slug = pick(rnd, SLUGS);
  const pin = pick(rnd, PINCODES);
  const hour = 3 + Math.floor(rnd() * 14);
  const start = Date.UTC(+day.slice(0, 4), +day.slice(5, 7) - 1, +day.slice(8, 10), hour, Math.floor(rnd() * 60), Math.floor(rnd() * 60));

  let unit: UnitDef | null = null;
  let blocker: BlockerId | "converted" = "converted";
  if (isHuman) {
    blocker = rnd() < 0.06 ? "converted" : "B99";
  } else if (rnd() < (phase === "before" ? 0.06 : 0.14)) {
    unit = weightedPick(rnd, UNITS, UNITS.map((u) => u.convShare));
    blocker = "converted";
  } else {
    const defs = BLOCKERS.filter((b) => b[phase] > 0);
    const def = weightedPick(rnd, defs, defs.map((b) => b[phase]));
    blocker = def.id;
    const eligible = UNITS.filter((u) => applies(def, u));
    unit = weightedPick(rnd, eligible, eligible.map((u) => u.share));
  }

  const human = isHuman;
  const j = human
    ? blocker === "converted"
      ? journeyFor("converted", slug, pin, null, rnd)
      : { reqs: baseSteps(slug, pin, 1 + Math.floor(rnd() * 4), true, rnd), maxStage: "S2" as StageId, evidence: [], summary: "" }
    : journeyFor(blocker, slug, pin, unit, rnd);

  const sessionId = idFrom(rnd, "ses_", 10);
  let t = start;
  const requests: SessionRequest[] = j.reqs.map((r, i) => {
    t += i === 0 ? 0 : r.gap ?? Math.round((human ? 4000 : 400) + rnd() * (human ? 20000 : 3500));
    return {
      request_id: idFrom(rnd, "req_", 10),
      ts: new Date(t).toISOString(),
      offset_ms: t - start,
      method: r.method,
      path: r.path,
      status: r.status,
      duration_ms: r.dur,
      page_type: r.type ?? null,
      error_code: r.err ?? null,
      stage_id: r.stage ?? null,
      is_asset: !!r.asset,
    };
  });
  const ids = requests.map((r) => r.request_id);
  const terminalReqIds = ids.slice(-1);
  const evidence: EvidenceItem[] =
    typeof j.evidence === "function"
      ? j.evidence(terminalReqIds.length ? ids : [""])
      : j.evidence.map((e) => (e.type === "request" && !e.request_id ? { ...e, request_id: ids[ids.length - 1] } : e));

  const converted = blocker === "converted";
  const tier = human ? "human" : unit!.tier;
  const conf = human ? 0.9 : tier === "verified" ? 1 : tier === "declared" ? (rnd() < 0.5 ? 0.9 : 0.7) : +(0.6 + rnd() * 0.32).toFixed(2);
  const pages = requests.filter((r) => !r.is_asset && r.method === "GET" && r.status < 400 && r.page_type && r.page_type !== "api").length;
  const lastTs = t;
  const terminalDef = !human && !converted ? BLOCKER_BY_ID[blocker as BlockerId] : null;
  const bconf = terminalDef ? (blocker === "B99" ? null : +(0.62 + rnd() * 0.35).toFixed(2)) : null;
  const order = converted ? Math.round((1400 + rnd() * 2600) / 10) * 10 : null;

  const row: SessionRow = {
    session_id: sessionId,
    start_ts: new Date(start).toISOString(),
    duration_s: Math.max(1, Math.round((lastTs - start) / 1000)),
    request_count: requests.length,
    page_count: pages,
    identity_tier: tier,
    operator: human ? "human" : unit!.operator,
    agent_name: human ? "Browser (human)" : unit!.agent_name,
    agent_class: human ? "human" : unit!.agent_class,
    identity_confidence: conf,
    entry_page: requests.find((r) => !r.is_asset)?.path ?? "/",
    exit_page: [...requests].reverse().find((r) => !r.is_asset)?.path ?? "/",
    max_stage: converted ? "S8" : j.maxStage,
    converted,
    order_value_inr: order,
    terminal_blocker_id: terminalDef ? terminalDef.id : null,
    terminal_blocker_name: terminalDef ? terminalDef.name : null,
    blocker_confidence: bconf,
    diagnosis_method: terminalDef ? (blocker === "B99" ? (rnd() < 0.5 ? "llm" : "none") : "rule") : "none",
  };

  const fired: FiredRule[] = [];
  if (terminalDef && blocker !== "B99") {
    fired.push({
      blocker_id: terminalDef.id, name: terminalDef.name, stage: terminalDef.stage,
      confidence: bconf ?? 0.8, is_terminal: true, evidence,
    });
    if (!human && unit!.agent_class === "browsing_agent" && terminalDef.id !== "B07" && rnd() < 0.25) {
      fired.push({
        blocker_id: "B07", name: BLOCKER_BY_ID.B07.name, stage: "S2", confidence: 0.41, is_terminal: false,
        evidence: [{ type: "request", request_id: ids[Math.min(1, ids.length - 1)], summary: "Overlay detected on the landing page (no interaction for 12 s)" }],
      });
    }
  }

  let sig: SignatureStatus = "none";
  if (tier === "verified") sig = "valid";
  else if (tier === "declared") sig = rnd() < 0.04 ? "expired" : rnd() < 0.03 ? "invalid_sig" : "none";
  else if (tier === "suspected") sig = rnd() < 0.08 ? "invalid_sig" : "none";

  const stageSeen = new Map<StageId, string>();
  for (const r of requests) if (r.stage_id && !stageSeen.has(r.stage_id)) stageSeen.set(r.stage_id, r.ts);

  const detail: SessionDetail = {
    session: row,
    identity: {
      signature_status: sig,
      signature_agent: human ? null : unit!.signatureAgent,
      suspicion_score: tier === "suspected" ? Math.round(conf * 100) : tier === "human" ? Math.round(rnd() * 25) : null,
      user_agent: human ? "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/131.0 Mobile Safari/537.36" : unit!.ua,
      ip_match: tier === "declared" ? rnd() < 0.55 : null,
    },
    requests,
    stage_events: [...stageSeen.entries()].map(([stage_id, first_reached_ts]) => ({ stage_id, first_reached_ts })),
    fired_rules: fired,
    replay_ids: [],
  };
  return { row, detail };
}

function generate() {
  const rnd = mulberry32(20261118);
  for (const day of DAYS) {
    const n = 20 + Math.floor(rnd() * 6);
    for (let k = 0; k < n; k++) SEEDS.push(buildSession(day, rnd));
  }
  SEEDS.sort((a, b) => b.row.start_ts.localeCompare(a.row.start_ts));
}
generate();

export const SESSIONS: SessionRow[] = SEEDS.map((s) => s.row);

export function sessionDetail(id: string): SessionDetail | null {
  return SEEDS.find((s) => s.row.session_id === id)?.detail ?? null;
}

export function sampleSessionsFor(blocker: BlockerId, from: string, to: string, n: number): SessionRow[] {
  return SESSIONS.filter((s) => s.terminal_blocker_id === blocker && s.start_ts.slice(0, 10) >= from && s.start_ts.slice(0, 10) <= to).slice(0, n);
}

/** Attach replay ids to their source sessions (called once replays are built). */
export function linkReplay(sessionId: string, replayId: string) {
  const d = SEEDS.find((s) => s.row.session_id === sessionId)?.detail;
  if (d && !d.replay_ids.includes(replayId)) d.replay_ids.push(replayId);
}
