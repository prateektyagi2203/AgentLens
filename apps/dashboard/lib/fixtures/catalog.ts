import type {
  AgentClass,
  BlockerId,
  Effort,
  IdentityTier,
  Owner,
  StageId,
} from "../types";

export const STAGES: { id: StageId; name: string }[] = [
  { id: "S1", name: "Landing / Search" },
  { id: "S2", name: "Product page" },
  { id: "S3", name: "Variant selected" },
  { id: "S4", name: "Delivery check" },
  { id: "S5", name: "Added to cart" },
  { id: "S6", name: "Checkout started" },
  { id: "S7", name: "Checkout submitted" },
  { id: "S8", name: "Order placed" },
];

export const stageNum = (s: StageId): number => Number(s.slice(1));

/** P(convert | passed stage), the p_s of PRD 14.1, used by the mock impact model. */
export const STAGE_P: Record<StageId, number> = {
  S1: 0.03,
  S2: 0.04,
  S3: 0.07,
  S4: 0.1,
  S5: 0.18,
  S6: 0.3,
  S7: 0.4,
  S8: 1,
};

export const EFFORT_WEIGHT: Record<Effort, number> = { S: 1, M: 2, L: 4 };

export interface BlockerDef {
  id: BlockerId;
  name: string;
  stage: StageId;
  effort: Effort;
  owner: Owner;
  description: string;
  detection: string;
  errorCodes: [string, number][];
  examples: string[];
  rec: { title: string; body: string; why: string; verifyMetric: string; verify: string };
  /** Which agent classes the blocker can hit (F = user_fetcher, B = browsing_agent). */
  affinity: "F" | "B" | "A" | "A_unverified";
  /** Sessions blocked in the 7-day "before" and "after" phases of the demo story. */
  before: number;
  after: number;
}

export const BLOCKERS: BlockerDef[] = [
  {
    id: "B01",
    name: "Bot wall / WAF block",
    stage: "S1",
    effort: "M",
    owner: "Security",
    description:
      "A WAF or bot-management rule answers identified agents with a 403/503 challenge page, so they never see the catalogue.",
    detection: "Status 403/503 with challenge markers, or a 403 as the last request, while agent identity is present.",
    errorCodes: [["WAF_CHALLENGE", 0.82], ["FORBIDDEN", 0.18]],
    examples: ["GET /p/white-court-sneaker → 403 (challenge page) · agent: ChatGPT-User (Declared)"],
    rec: {
      title: "Allow-list verified agents, challenge only suspicious traffic",
      body: "Add Web Bot Auth verified operators to the WAF allow-list and switch Declared agents to a risk-based challenge instead of a hard block.",
      why: "Agents cannot solve interactive challenges, so every block ends the journey immediately.",
      verifyMetric: "403 share of agent requests",
      verify: "403/503 responses to Verified and Declared agents should fall to near zero.",
    },
    affinity: "A_unverified",
    before: 80,
    after: 110,
  },
  {
    id: "B02",
    name: "Captcha",
    stage: "S6",
    effort: "M",
    owner: "Security",
    description: "A captcha appears at checkout and the agent never submits a solution.",
    detection: "Session reaches checkout, a captcha endpoint or page is requested, and no successful submit follows.",
    errorCodes: [["CAPTCHA_REQUIRED", 1]],
    examples: ["GET /checkout → 200 · GET /captcha/challenge → 200 · session ended"],
    rec: {
      title: "Use risk-based challenges, skip captcha for verified agents",
      body: "Remove the unconditional checkout captcha and challenge only sessions with a high risk score.",
      why: "Captchas are built to stop automation, including agents acting for a paying shopper.",
      verifyMetric: "Checkout started → submitted conversion",
      verify: "Step conversion from S6 to S7 should rise for agents.",
    },
    affinity: "B",
    before: 0,
    after: 70,
  },
  {
    id: "B03",
    name: "JS-only price and stock",
    stage: "S2",
    effort: "M",
    owner: "Eng",
    description:
      "Price and stock are rendered by client-side JavaScript. Agents that fetch HTML see a product with no price or availability and give up.",
    detection:
      "A user_fetcher session fetched the product page and ended; the site check shows price/stock missing from server HTML and JSON-LD.",
    errorCodes: [["PRICE_NOT_IN_HTML", 1]],
    examples: ["Site check: price not found in server HTML or JSON-LD on 5/5 sampled PDPs"],
    rec: {
      title: "Server-render price and stock, and include them in JSON-LD",
      body: "Render price, currency and availability in the initial HTML and add a complete schema.org Offer to each product page.",
      why: "Fetch-based agents never run your JavaScript, so anything rendered client-side is invisible to them.",
      verifyMetric: "PDP → variant step conversion (fetchers)",
      verify: "Step conversion S2 → S3 for user_fetcher sessions should rise.",
    },
    affinity: "F",
    before: 600,
    after: 0,
  },
  {
    id: "B04",
    name: "Missing structured data",
    stage: "S2",
    effort: "S",
    owner: "Content",
    description: "Product pages lack complete schema.org Product markup (price, availability, variants).",
    detection: "Site check: JSON-LD Product missing or incomplete.",
    errorCodes: [["JSONLD_INCOMPLETE", 1]],
    examples: ["Site check: JSON-LD Product missing availability on 2/5 sampled PDPs"],
    rec: {
      title: "Add complete schema.org Product markup",
      body: "Emit Product, Offer and ItemAvailability for every variant in JSON-LD.",
      why: "Structured data is the cheapest reliable way for agents to read product facts.",
      verifyMetric: "Site check: jsonld_product",
      verify: "The JSON-LD site check should pass on all sampled PDPs.",
    },
    affinity: "F",
    before: 50,
    after: 60,
  },
  {
    id: "B05",
    name: "Pincode wall",
    stage: "S5",
    effort: "S",
    owner: "Product",
    description:
      "Add-to-cart is rejected with 409 PINCODE_REQUIRED until a delivery pincode is entered in a modal. Agents cannot find or fill it and leave.",
    detection:
      "Add-to-cart returned 409 PINCODE_REQUIRED, or repeated serviceability calls failed, or the session ended within 2 requests after the PDP with serviceability required.",
    errorCodes: [["PINCODE_REQUIRED", 0.92], ["PINCODE_UNSERVICEABLE", 0.08]],
    examples: ["POST /api/cart → 409 PINCODE_REQUIRED (×2) · session ended 4 s later"],
    rec: {
      title: "Make the pincode optional before cart",
      body: "Accept the pincode via URL or API, default to a metro pincode, and show the delivery promise inline instead of a blocking modal.",
      why: "92% of the failures are a 409 on add-to-cart. Agents cannot operate a modal they were never told about.",
      verifyMetric: "Step conversion S4 → S5 for agents",
      verify: "Delivery check → Added to cart step conversion for agents should rise, and B05 should drop out of the blocker list.",
    },
    affinity: "B",
    before: 1240,
    after: 0,
  },
  {
    id: "B06",
    name: "Login / OTP wall before cart",
    stage: "S5",
    effort: "M",
    owner: "Product",
    description: "Cart creation requires a logged-in user. The agent is redirected to an OTP login it cannot complete.",
    detection: "Cart POST returned 401, redirect to /login, OTP sent without a verify, session ended.",
    errorCodes: [["UNAUTHENTICATED", 0.74], ["OTP_SENT_NO_VERIFY", 0.26]],
    examples: ["POST /api/cart → 401 → GET /login → POST /api/otp/send · no verify · ended"],
    rec: {
      title: "Allow guest cart, defer login to checkout",
      body: "Let anonymous sessions create carts and ask for login (or guest checkout) only at payment.",
      why: "An SMS OTP goes to the shopper's phone, so an agent cannot complete it.",
      verifyMetric: "Step conversion S4 → S5 for agents",
      verify: "401 responses on POST /api/cart should disappear and add-to-cart step conversion should rise.",
    },
    affinity: "B",
    before: 480,
    after: 0,
  },
  {
    id: "B07",
    name: "App-download interstitial",
    stage: "S2",
    effort: "S",
    owner: "Product",
    description:
      "A full-screen 'get the app' overlay covers the landing and product pages. Browsing agents see no clickable content and stall.",
    detection:
      "Browsing agent with beacons but no further interaction after landing or PDP within the threshold; a replay confirms the overlay.",
    errorCodes: [["OVERLAY_NO_INTERACTION", 1]],
    examples: ["GET /p/white-court-sneaker → 200 · beacon seen · no further request for 41 s"],
    rec: {
      title: "Delay or remove the interstitial and keep a close button",
      body: "Never block content with an overlay; show the app banner inline and give it an accessible close control.",
      why: "Agents interpret the overlay as the page content and cannot dismiss it reliably.",
      verifyMetric: "Landing → product step conversion (browsing agents)",
      verify: "Step conversion S1 → S2 for browsing agents should rise.",
    },
    affinity: "B",
    before: 320,
    after: 1075,
  },
  {
    id: "B08",
    name: "Out-of-stock dead end",
    stage: "S3",
    effort: "S",
    owner: "Product",
    description: "The chosen variant is out of stock and the page offers no alternative the agent can pick up.",
    detection: "Variant API returned 409 out of stock as the last meaningful request with no alternative variant requested.",
    errorCodes: [["VARIANT_OUT_OF_STOCK", 1]],
    examples: ["GET /api/products/white-court-sneaker/variants?size=9 → 409 VARIANT_OUT_OF_STOCK · ended"],
    rec: {
      title: "Suggest in-stock alternatives",
      body: "Expose availability per variant in HTML and JSON-LD and link to the nearest in-stock size or colour.",
      why: "A dead end gives an agent no next action, so it reports failure to the shopper.",
      verifyMetric: "Variant API 409 share",
      verify: "Sessions ending on a 409 variant response should fall.",
    },
    affinity: "A",
    before: 120,
    after: 330,
  },
  {
    id: "B09",
    name: "Size guide image-only",
    stage: "S3",
    effort: "S",
    owner: "Content",
    description: "The size guide is a single image. Agents cannot read it, cannot pick a size and stop before the cart.",
    detection: "Size guide requested, served as an image, session ended before cart.",
    errorCodes: [["SIZE_GUIDE_IMAGE", 1]],
    examples: ["GET /size-guide/white-court-sneaker.png → 200 (image/png) · session ended before cart"],
    rec: {
      title: "Provide an HTML size table",
      body: "Replace the size chart image with an HTML table (and keep the image as a visual aid).",
      why: "Agents rely on text. An image-only chart hides the information they need to choose a size.",
      verifyMetric: "Variant selected → delivery check step conversion",
      verify: "Step conversion S3 → S4 should rise and size guide requests should stop ending sessions.",
    },
    affinity: "A",
    before: 260,
    after: 1000,
  },
  {
    id: "B10",
    name: "Checkout validation failure",
    stage: "S7",
    effort: "S",
    owner: "Eng",
    description:
      "Checkout rejects phone numbers that are not in the exact +91 format the form expects, so agents loop on 422 errors.",
    detection: "Repeated 400/422 on checkout submit with field error codes such as PHONE_FORMAT.",
    errorCodes: [["PHONE_FORMAT", 0.86], ["PINCODE_FORMAT", 0.14]],
    examples: ["POST /api/checkout → 422 PHONE_FORMAT (×3)"],
    rec: {
      title: "Normalise phone numbers and relax validation",
      body: "Accept +91, 91, 0 and bare 10-digit variants, normalise server-side and return a human-readable error.",
      why: "Agents type numbers in the format the shopper gave them and rarely retry with a different one.",
      verifyMetric: "Checkout submit 422 rate",
      verify: "POST /api/checkout 422 PHONE_FORMAT responses should fall and S6 → S7 step conversion should rise.",
    },
    affinity: "B",
    before: 200,
    after: 380,
  },
  {
    id: "B11",
    name: "Unsupported payment step",
    stage: "S7",
    effort: "L",
    owner: "Product",
    description: "The only available payment options are a COD OTP and a UPI intent flow that an agent cannot complete.",
    detection: "COD OTP step or UPI intent step reached with no completion.",
    errorCodes: [["COD_OTP_REQUIRED", 0.6], ["UPI_INTENT_ONLY", 0.4]],
    examples: ["POST /api/checkout → 200 · GET /api/payment/cod-otp → 200 · no verify · ended"],
    rec: {
      title: "Offer an agent-compatible payment option",
      body: "Add card tokens or a prepaid payment link and skip the COD OTP for verified agents.",
      why: "The shopper's phone receives the OTP and the UPI app opens on a device the agent does not control.",
      verifyMetric: "Checkout submitted → order placed step conversion",
      verify: "Step conversion S7 → S8 should rise for agents.",
    },
    affinity: "B",
    before: 40,
    after: 170,
  },
  {
    id: "B12",
    name: "Rate limited",
    stage: "S1",
    effort: "S",
    owner: "Security",
    description: "The agent hits a 429 and does not retry.",
    detection: "429 responses and the session ends after.",
    errorCodes: [["RATE_LIMITED", 1]],
    examples: ["GET /p/white-court-sneaker → 429 Retry-After: 60 · ended"],
    rec: {
      title: "Higher limits for verified agents, add Retry-After",
      body: "Raise the per-IP limit for Verified agents and always return a Retry-After header.",
      why: "Agents act in bursts from shared IPs and treat a 429 as a hard stop.",
      verifyMetric: "429 share of agent requests",
      verify: "429 responses to Verified agents should fall to near zero.",
    },
    affinity: "A",
    before: 60,
    after: 80,
  },
  {
    id: "B13",
    name: "Slow response / timeout",
    stage: "S1",
    effort: "M",
    owner: "Eng",
    description: "A request takes longer than the agent's patience, or is abandoned in flight.",
    detection: "Last request duration over the threshold (default 5 s) or abandoned in flight.",
    errorCodes: [["TIMEOUT", 1]],
    examples: ["GET /c/sneakers → 504 after 7.4 s · ended"],
    rec: {
      title: "Cache listing and product pages",
      body: "Serve cached HTML for listing and product pages and investigate the slow endpoints.",
      why: "Agents run on a tight time budget and abandon slow pages.",
      verifyMetric: "p95 response time for agent sessions",
      verify: "p95 should fall below the 5 s threshold.",
    },
    affinity: "A",
    before: 50,
    after: 70,
  },
  {
    id: "B14",
    name: "robots.txt disallow",
    stage: "S1",
    effort: "S",
    owner: "Content",
    description: "The agent fetched robots.txt, found its token disallowed, and left.",
    detection: "Agent fetched robots.txt, the path is disallowed for its token, the agent left.",
    errorCodes: [["ROBOTS_DISALLOW", 1]],
    examples: ["GET /robots.txt → 200 · User-agent: ChatGPT-User Disallow: /"],
    rec: {
      title: "Review the robots policy for user-triggered agents",
      body: "Allow user-triggered fetchers that act for a shopper while keeping training crawlers blocked if desired.",
      why: "A user-triggered agent honouring robots.txt cannot complete a purchase the shopper asked for.",
      verifyMetric: "Site check: robots_txt",
      verify: "The robots site check should pass for user-triggered agents.",
    },
    affinity: "F",
    before: 20,
    after: 25,
  },
  {
    id: "B15",
    name: "Price mismatch PDP vs cart",
    stage: "S6",
    effort: "M",
    owner: "Eng",
    description: "The cart total differs from the product page price and the agent stops.",
    detection: "Cart value differs from the sum of PDP prices seen in the session and the session ends.",
    errorCodes: [["PRICE_MISMATCH", 1]],
    examples: ["PDP ₹2,199 · cart ₹2,499 · session ended"],
    rec: {
      title: "Show the same price everywhere",
      body: "Fix pricing consistency between product page, cart and checkout.",
      why: "Agents verify the price against the one they were asked to stay under.",
      verifyMetric: "Cart/PDP price mismatch rate",
      verify: "Mismatch rate between PDP and cart should be zero.",
    },
    affinity: "B",
    before: 10,
    after: 60,
  },
  {
    id: "B16",
    name: "Broken link / 404",
    stage: "S2",
    effort: "S",
    owner: "Content",
    description: "An old product or checkout URL returns 404 and the agent has no way forward.",
    detection: "404 as the last request on a product or checkout path.",
    errorCodes: [["NOT_FOUND", 1]],
    examples: ["GET /p/white-court-sneaker-old → 404 · ended"],
    rec: {
      title: "Fix links and redirect old URLs",
      body: "Add 301 redirects for retired product URLs and fix broken internal links.",
      why: "Agents cannot recover from a 404 the way a human would by searching again.",
      verifyMetric: "404 share on product paths",
      verify: "404 responses on /p/* should fall.",
    },
    affinity: "A",
    before: 30,
    after: 40,
  },
  {
    id: "B99",
    name: "Unknown",
    stage: "S4",
    effort: "M",
    owner: "Eng",
    description: "No rule fired. The session needs the LLM classifier or manual review.",
    detection: "Nothing fired.",
    errorCodes: [["NONE", 1]],
    examples: ["GET /c/sneakers → 200 · GET /p/white-court-sneaker → 200 · ended"],
    rec: {
      title: "Review unknown sessions",
      body: "Run the LLM classifier on the unknown sessions or replay a sample manually to find new blocker patterns.",
      why: "Unexplained failures hide the next fix.",
      verifyMetric: "Diagnosis coverage",
      verify: "Diagnosis coverage should rise above 90%.",
    },
    affinity: "A",
    before: 440,
    after: 520,
  },
];

export const BLOCKER_BY_ID = Object.fromEntries(BLOCKERS.map((b) => [b.id, b])) as Record<BlockerId, BlockerDef>;

export interface UnitDef {
  id: string;
  operator: string;
  agent_name: string;
  agent_class: Extract<AgentClass, "user_fetcher" | "browsing_agent">;
  tier: Exclude<IdentityTier, "human">;
  /** Relative share of agent traffic. */
  share: number;
  /** Relative share of agent conversions. */
  convShare: number;
  pages: number;
  ua: string;
  signatureAgent: string | null;
}

export const UNITS: UnitDef[] = [
  {
    id: "U1", operator: "OpenAI", agent_name: "ChatGPT agent", agent_class: "browsing_agent", tier: "verified",
    share: 0.18, convShare: 0.34, pages: 8.2,
    ua: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
    signatureAgent: "https://chatgpt.com",
  },
  {
    id: "U2", operator: "OpenAI", agent_name: "ChatGPT agent", agent_class: "browsing_agent", tier: "declared",
    share: 0.08, convShare: 0.12, pages: 7.4,
    ua: "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ChatGPT-Agent/1.0)",
    signatureAgent: null,
  },
  {
    id: "U3", operator: "OpenAI", agent_name: "ChatGPT-User", agent_class: "user_fetcher", tier: "declared",
    share: 0.2, convShare: 0.05, pages: 2.9,
    ua: "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ChatGPT-User/1.0; +https://openai.com/bot",
    signatureAgent: null,
  },
  {
    id: "U4", operator: "Anthropic", agent_name: "Claude-User", agent_class: "user_fetcher", tier: "declared",
    share: 0.12, convShare: 0.03, pages: 2.4,
    ua: "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-User/1.0; +Claude-User@anthropic.com)",
    signatureAgent: null,
  },
  {
    id: "U5", operator: "Perplexity", agent_name: "Perplexity-User", agent_class: "user_fetcher", tier: "declared",
    share: 0.12, convShare: 0.03, pages: 2.2,
    ua: "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Perplexity-User/1.0; +https://perplexity.ai/perplexity-user)",
    signatureAgent: null,
  },
  {
    id: "U6", operator: "unknown", agent_name: "Unidentified browsing agent", agent_class: "browsing_agent", tier: "suspected",
    share: 0.11, convShare: 0.17, pages: 6.8,
    ua: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 HeadlessChrome/130.0 Safari/537.36",
    signatureAgent: null,
  },
  {
    id: "U7", operator: "Google", agent_name: "Gemini agent", agent_class: "browsing_agent", tier: "declared",
    share: 0.07, convShare: 0.12, pages: 7.0,
    ua: "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/131.0 Mobile Safari/537.36 Google-Agent",
    signatureAgent: null,
  },
  {
    id: "U8", operator: "TestOperator", agent_name: "AgentLens Test Agent", agent_class: "browsing_agent", tier: "verified",
    share: 0.04, convShare: 0.1, pages: 7.8,
    ua: "AgentLens-Synth/1.0 (+https://agents.desithreads.test)",
    signatureAgent: "https://agents.desithreads.test",
  },
  {
    id: "U9", operator: "unknown", agent_name: "Unidentified fetcher", agent_class: "user_fetcher", tier: "suspected",
    share: 0.08, convShare: 0.04, pages: 2.6,
    ua: "python-requests/2.32",
    signatureAgent: null,
  },
];

export const CRAWLERS: {
  operator: string;
  agent_name: string;
  agent_class: "search_crawler" | "training_crawler";
  requests: number;
  pagesPerReq: number;
  robots: boolean;
}[] = [
  { operator: "Google", agent_name: "Googlebot", agent_class: "search_crawler", requests: 41_200, pagesPerReq: 0.82, robots: true },
  { operator: "Microsoft", agent_name: "Bingbot", agent_class: "search_crawler", requests: 17_800, pagesPerReq: 0.8, robots: true },
  { operator: "OpenAI", agent_name: "OAI-SearchBot", agent_class: "search_crawler", requests: 6_900, pagesPerReq: 0.9, robots: true },
  { operator: "OpenAI", agent_name: "GPTBot", agent_class: "training_crawler", requests: 12_400, pagesPerReq: 0.86, robots: true },
  { operator: "Anthropic", agent_name: "ClaudeBot", agent_class: "training_crawler", requests: 9_300, pagesPerReq: 0.84, robots: true },
  { operator: "Perplexity", agent_name: "PerplexityBot", agent_class: "search_crawler", requests: 4_100, pagesPerReq: 0.88, robots: false },
  { operator: "Common Crawl", agent_name: "CCBot", agent_class: "training_crawler", requests: 3_300, pagesPerReq: 0.9, robots: true },
];

export const HUMAN_STAGE_REACH = [1, 0.55, 0.34, 0.22, 0.13, 0.085, 0.056, 0.042];

export const OPERATORS = ["Anthropic", "Google", "OpenAI", "Perplexity", "TestOperator", "unknown"];
