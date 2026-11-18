import type { BlockerId, ReplayDetail, ReplayRow, ReplayStep, ReplayVerdict, NetworkLogEntry } from "../types";
import { BLOCKER_BY_ID } from "./catalog";
import { SESSIONS, linkReplay } from "./sessions";

type Scene =
  | "landing"
  | "pdp"
  | "pdp_no_price"
  | "variant"
  | "delivery"
  | "pincode_modal"
  | "login_otp"
  | "app_overlay"
  | "size_guide_image"
  | "checkout_error"
  | "out_of_stock";

interface StepDef {
  action: string;
  method: string;
  url: string;
  status: number;
  note: string;
  scene: Scene;
  error?: string;
}

interface ReplayDef {
  id: string;
  blocker: BlockerId;
  mode: "fetch" | "browser";
  verdict: ReplayVerdict;
  startedAt: string;
  sessionIndex: number;
  explanation: string;
  steps: StepDef[];
}

const S = "/p/white-court-sneaker";

const DEFS: ReplayDef[] = [
  {
    id: "rpl_b05_a", blocker: "B05", mode: "browser", verdict: "confirmed", startedAt: "2026-11-11T17:02:10Z", sessionIndex: 0,
    explanation:
      "Confirmed. The test agent reproduced the journey: add-to-cart returned 409 PINCODE_REQUIRED and a blocking 'Enter delivery pincode' modal appeared. The agent had no way to continue without opening and filling the modal.",
    steps: [
      { action: "Open the landing page", method: "GET", url: "/", status: 200, note: "Landing page loads normally.", scene: "landing" },
      { action: "Open the product page", method: "GET", url: S, status: 200, note: "Price and sizes are visible.", scene: "pdp" },
      { action: "Choose size 9", method: "GET", url: "/api/products/white-court-sneaker/variants?size=9", status: 200, note: "Variant available.", scene: "variant" },
      { action: "Check delivery", method: "GET", url: "/api/serviceability?pincode=560001", status: 200, note: "Serviceability answered, but no pincode is stored for the session.", scene: "delivery" },
      { action: "Click “Add to cart”", method: "POST", url: "/api/cart", status: 409, note: "Cart rejected the request and a blocking pincode modal appeared. The agent stopped here.", scene: "pincode_modal", error: "PINCODE_REQUIRED" },
    ],
  },
  {
    id: "rpl_b05_b", blocker: "B05", mode: "browser", verdict: "confirmed", startedAt: "2026-11-11T17:09:42Z", sessionIndex: 1,
    explanation:
      "Confirmed a second time with a different product and a different pincode. Same 409 PINCODE_REQUIRED on add-to-cart, same modal.",
    steps: [
      { action: "Open the product page", method: "GET", url: "/p/indigo-kurta-set", status: 200, note: "Product page loads.", scene: "pdp" },
      { action: "Choose size M", method: "GET", url: "/api/products/indigo-kurta-set/variants?size=M", status: 200, note: "Variant available.", scene: "variant" },
      { action: "Click “Add to cart”", method: "POST", url: "/api/cart", status: 409, note: "409 PINCODE_REQUIRED again.", scene: "pincode_modal", error: "PINCODE_REQUIRED" },
    ],
  },
  {
    id: "rpl_b03", blocker: "B03", mode: "fetch", verdict: "confirmed", startedAt: "2026-11-11T17:14:03Z", sessionIndex: 0,
    explanation:
      "Confirmed. A plain HTTP fetch of the product page returned 200 but neither the server HTML nor the JSON-LD contains a price or stock status; both are filled in by JavaScript after load. Fetch-mode replays take no screenshots.",
    steps: [
      { action: "Fetch the product page (no JavaScript)", method: "GET", url: S, status: 200, note: "HTML received. Searched for price: not found in HTML or JSON-LD (0 of 5 sampled PDPs expose it).", scene: "pdp_no_price" },
    ],
  },
  {
    id: "rpl_b06", blocker: "B06", mode: "browser", verdict: "confirmed", startedAt: "2026-11-11T17:21:30Z", sessionIndex: 0,
    explanation:
      "Confirmed. Add-to-cart returned 401 and redirected to /login, where an SMS OTP was sent to a phone the agent does not control.",
    steps: [
      { action: "Open the product page", method: "GET", url: S, status: 200, note: "Product page loads.", scene: "pdp" },
      { action: "Click “Add to cart”", method: "POST", url: "/api/cart", status: 401, note: "Cart requires a logged-in user.", scene: "pdp", error: "UNAUTHENTICATED" },
      { action: "Redirected to login", method: "GET", url: "/login", status: 200, note: "Login page asks for a mobile number.", scene: "login_otp" },
      { action: "Request OTP", method: "POST", url: "/api/otp/send", status: 200, note: "OTP sent to the shopper's phone. The agent cannot read it, so the journey ends.", scene: "login_otp", error: "OTP_SENT_NO_VERIFY" },
    ],
  },
  {
    id: "rpl_b07", blocker: "B07", mode: "browser", verdict: "confirmed", startedAt: "2026-11-11T17:28:11Z", sessionIndex: 0,
    explanation:
      "Confirmed. A full-screen 'Get the app' overlay covered the landing page and product page. The close control is a small unlabeled icon, and the agent saw no clickable product content.",
    steps: [
      { action: "Open the landing page", method: "GET", url: "/", status: 200, note: "Overlay covers the whole viewport.", scene: "app_overlay" },
      { action: "Try to continue to a product", method: "GET", url: S, status: 200, note: "Overlay appears again on the product page.", scene: "app_overlay" },
    ],
  },
  {
    id: "rpl_b09", blocker: "B09", mode: "fetch", verdict: "confirmed", startedAt: "2026-11-11T17:33:50Z", sessionIndex: 0,
    explanation:
      "Confirmed. The size guide is served as a PNG (image/png) with no text alternative or HTML table, so a text-reading agent cannot choose a size.",
    steps: [
      { action: "Fetch the product page", method: "GET", url: S, status: 200, note: "Page links to a size guide.", scene: "pdp" },
      { action: "Fetch the size guide", method: "GET", url: "/size-guide/white-court-sneaker.png", status: 200, note: "Content-Type: image/png. No alt text or HTML table.", scene: "size_guide_image" },
    ],
  },
  {
    id: "rpl_b10", blocker: "B10", mode: "browser", verdict: "confirmed", startedAt: "2026-11-11T17:41:25Z", sessionIndex: 0,
    explanation:
      "Confirmed. Submitting checkout with the phone number +91 98765 43210 returned 422 PHONE_FORMAT three times; the form only accepts a bare 10-digit number.",
    steps: [
      { action: "Open checkout", method: "GET", url: "/checkout", status: 200, note: "Checkout form loads.", scene: "checkout_error" },
      { action: "Submit with +91 98765 43210", method: "POST", url: "/api/checkout", status: 422, note: "Validation error under the phone field.", scene: "checkout_error", error: "PHONE_FORMAT" },
      { action: "Retry with 91 98765 43210", method: "POST", url: "/api/checkout", status: 422, note: "Same error. The agent gave up after three tries.", scene: "checkout_error", error: "PHONE_FORMAT" },
    ],
  },
  {
    id: "rpl_b08", blocker: "B08", mode: "browser", verdict: "inconclusive", startedAt: "2026-11-11T17:48:00Z", sessionIndex: 0,
    explanation:
      "Inconclusive. The variant was in stock when replayed, so the out-of-stock dead end could not be reproduced. The source session may have hit a transient stock state.",
    steps: [
      { action: "Open the product page", method: "GET", url: S, status: 200, note: "Product page loads.", scene: "pdp" },
      { action: "Choose size 9", method: "GET", url: "/api/products/white-court-sneaker/variants?size=9", status: 200, note: "Variant in stock this time.", scene: "variant" },
    ],
  },
];

const T0 = (iso: string, plusMs: number) => new Date(Date.parse(iso) + plusMs).toISOString();

function sourceSession(def: ReplayDef): string {
  const pool = SESSIONS.filter((s) => s.terminal_blocker_id === def.blocker && s.start_ts < "2026-11-12");
  return (pool[def.sessionIndex] ?? pool[0] ?? SESSIONS[0]).session_id;
}

export const REPLAY_ROWS: ReplayRow[] = DEFS.map((d) => ({
  replay_id: d.id,
  blocker_id: d.blocker,
  blocker_name: BLOCKER_BY_ID[d.blocker].name,
  source_session_id: sourceSession(d),
  mode: d.mode,
  status: "completed",
  verdict: d.verdict,
  started_at: d.startedAt,
  finished_at: T0(d.startedAt, d.steps.length * 2600 + 1500),
  steps_count: d.steps.length,
  verdict_explanation: d.explanation,
}));

REPLAY_ROWS.forEach((r) => linkReplay(r.source_session_id, r.replay_id));

export function replayDetail(id: string): ReplayDetail | null {
  const row = REPLAY_ROWS.find((r) => r.replay_id === id);
  const def = DEFS.find((d) => d.id === id);
  if (!row || !def) return null;
  const steps: ReplayStep[] = def.steps.map((s, i) => ({
    n: i + 1,
    action: s.action,
    method: s.method,
    url: s.url,
    status: s.status,
    duration_ms: 120 + ((i * 97 + def.id.length * 13) % 260),
    note: s.note,
    screenshot_url: def.mode === "browser" ? `/demo/replays/${id}/step_${i + 1}.svg` : null,
  }));
  const network_log: NetworkLogEntry[] = def.steps.map((s, i) => ({
    ts: T0(def.startedAt, i * 2600),
    method: s.method,
    url: s.url,
    status: s.status,
    duration_ms: steps[i].duration_ms,
    error_code: s.error ?? null,
  }));
  return {
    replay: row,
    user_agent: "AgentLens-Replay/1.0 (+https://github.com/<user>/agentlens)",
    signed_requests: false,
    steps,
    network_log,
    explanation: def.explanation,
  };
}

export const replayStatusFor = (blocker: BlockerId): ReplayVerdict | "not_run" => {
  const latest = [...REPLAY_ROWS]
    .filter((r) => r.blocker_id === blocker)
    .sort((a, b) => b.started_at.localeCompare(a.started_at))[0];
  return latest?.verdict ?? "not_run";
};

/** Scenes drive the generated SVG placeholders (scripts/generate-demo.ts). */
export function replayScenes(): { replay_id: string; n: number; scene: Scene; caption: string; status: number }[] {
  return DEFS.filter((d) => d.mode === "browser").flatMap((d) =>
    d.steps.map((s, i) => ({ replay_id: d.id, n: i + 1, scene: s.scene, caption: s.action, status: s.status })),
  );
}
