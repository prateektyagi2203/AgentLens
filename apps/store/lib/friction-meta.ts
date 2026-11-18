export const FRICTION_IDS = [
  "F01", "F02", "F03", "F04", "F05", "F06", "F07", "F08",
  "F09", "F10", "F11", "F12", "F13", "F14", "F15", "F16",
] as const;

export type FrictionId = (typeof FRICTION_IDS)[number];
export type Toggles = Record<FrictionId, boolean>;

export const FRICTION_LABELS: Record<FrictionId, { label: string; description: string }> = {
  F01: { label: "Bot wall", description: "Non-browser or known agent user agents get a 403 challenge page." },
  F02: { label: "Captcha at checkout", description: "Checkout needs a solved captcha before submit." },
  F03: { label: "JS-only price", description: "PDP price and stock are rendered client-side only." },
  F04: { label: "No structured data", description: "Removes JSON-LD from the PDP." },
  F05: { label: "Pincode wall", description: "Modal on PDP; add to cart rejected until a pincode is validated." },
  F06: { label: "OTP before cart", description: "Add to cart needs an OTP-verified session." },
  F07: { label: "App-download interstitial", description: "Full-screen overlay on first PDP view, close button hidden 3 s." },
  F08: { label: "Spin-the-wheel popup", description: "Email-capture popup covering the landing page." },
  F09: { label: "Size chart image-only", description: "Size guide is an image, no HTML table." },
  F10: { label: "Strict phone validation", description: "Phone must be exactly +91 XXXXX XXXXX." },
  F11: { label: "Price mismatch", description: "Cart price differs from PDP price for 2 products." },
  F12: { label: "Rate limit", description: "More than 20 requests/minute per client returns 429." },
  F13: { label: "Slow pages", description: "PDP adds 6 to 9 s latency." },
  F14: { label: "robots.txt disallow", description: "Disallows /p/ and /checkout for listed agent tokens." },
  F15: { label: "COD OTP confirm", description: "COD orders need an OTP confirmation step." },
  F16: { label: "Out-of-stock dead end", description: "OOS variant returns 409 with no alternatives." },
};

/** The "Before" demo state (PRD 8.3 / Appendix C). */
export const DEFAULT_TOGGLES: Toggles = {
  F01: false, F02: false, F03: true, F04: false,
  F05: true, F06: true, F07: true, F08: false,
  F09: true, F10: true, F11: false, F12: false,
  F13: false, F14: false, F15: false, F16: false,
};

export function allOff(): Toggles {
  return Object.fromEntries(FRICTION_IDS.map((id) => [id, false])) as Toggles;
}
