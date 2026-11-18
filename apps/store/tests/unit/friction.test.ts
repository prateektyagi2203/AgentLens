import { describe, expect, it } from "vitest";
import {
  RateLimiter, botWallBlocks, captchaRequired, cartGuard, cartUnitPrice, codOtpRequired, decideGate, oosPolicy,
  overlays, pdpDelayMs, pdpRender, phoneValid, robotsTxt, sizeGuideMode,
} from "../../lib/friction";
import { DEFAULT_TOGGLES, allOff, type FrictionId, type Toggles } from "../../lib/friction-meta";

const on = (...ids: FrictionId[]): Toggles => ({ ...allOff(), ...Object.fromEntries(ids.map((i) => [i, true])) });
const BROWSER = "Mozilla/5.0 (Windows NT 10.0) Chrome/126";

describe("default Before state", () => {
  it("has F03, F05, F06, F07, F09, F10 on and the rest off", () => {
    const enabled = Object.entries(DEFAULT_TOGGLES).filter(([, v]) => v).map(([k]) => k);
    expect(enabled.sort()).toEqual(["F03", "F05", "F06", "F07", "F09", "F10"]);
  });
});

describe("F01 bot wall", () => {
  it("blocks non-browser and known agent UAs only when on", () => {
    expect(botWallBlocks(on("F01"), "python-httpx/0.27")).toBe(true);
    expect(botWallBlocks(on("F01"), null)).toBe(true);
    expect(botWallBlocks(on("F01"), `${BROWSER} ChatGPT-User/1.0`)).toBe(true);
    expect(botWallBlocks(on("F01"), BROWSER)).toBe(false);
    expect(botWallBlocks(allOff(), "python-httpx/0.27")).toBe(false);
  });
  it("lets the AgentLens replay agent through", () => {
    expect(botWallBlocks(on("F01"), "AgentLens-Replay/1.0 (+https://example.org)")).toBe(false);
  });
  it("answers 403 BOT_CHALLENGE through the gate, but not for assets or admin", () => {
    const base = { rateKey: "k", now: 0, toggles: on("F01") };
    const blocked = decideGate({ ...base, path: "/", ua: "curl/8" }, new RateLimiter());
    expect(blocked).toMatchObject({ action: "block", status: 403, errorCode: "BOT_CHALLENGE" });
    expect(decideGate({ ...base, path: "/_next/static/a.js", ua: "curl/8" }, new RateLimiter()).action).toBe("allow");
    expect(decideGate({ ...base, path: "/admin", ua: "curl/8" }, new RateLimiter()).action).toBe("allow");
  });
});

describe("F02 captcha", () => {
  it("requires a solved captcha only when on", () => {
    expect(captchaRequired(on("F02"), false)).toBe(true);
    expect(captchaRequired(on("F02"), true)).toBe(false);
    expect(captchaRequired(allOff(), false)).toBe(false);
  });
});

describe("F03 / F04 PDP rendering", () => {
  it("moves price client-side with F03 and drops offers from JSON-LD", () => {
    expect(pdpRender(allOff())).toEqual({ priceInHtml: true, jsonLd: "full" });
    expect(pdpRender(on("F03"))).toEqual({ priceInHtml: false, jsonLd: "basic" });
  });
  it("removes JSON-LD entirely with F04", () => {
    expect(pdpRender(on("F04")).jsonLd).toBe("none");
    expect(pdpRender(on("F03", "F04")).jsonLd).toBe("none");
  });
});

describe("F05 / F06 cart guard", () => {
  it("returns 409 PINCODE_REQUIRED before 401 AUTH_REQUIRED", () => {
    const t = on("F05", "F06");
    expect(cartGuard(t, { pincodeOk: false, otpVerified: false })).toMatchObject({ status: 409, error_code: "PINCODE_REQUIRED" });
    expect(cartGuard(t, { pincodeOk: true, otpVerified: false })).toMatchObject({ status: 401, error_code: "AUTH_REQUIRED", redirect: "/login" });
    expect(cartGuard(t, { pincodeOk: true, otpVerified: true })).toBeNull();
  });
  it("lets everything through when off", () => {
    expect(cartGuard(allOff(), { pincodeOk: false, otpVerified: false })).toBeNull();
  });
});

describe("F07 / F08 overlays", () => {
  it("toggles the overlays and hides the close button for 3 s", () => {
    expect(overlays(on("F07", "F08"))).toMatchObject({ appInterstitial: true, spinWheel: true, closeDelayMs: 3000 });
    expect(overlays(allOff())).toMatchObject({ appInterstitial: false, spinWheel: false, pincodeModal: false });
  });
});

describe("F09 size guide", () => {
  it("is image-only when on", () => {
    expect(sizeGuideMode(on("F09"))).toBe("image-only");
    expect(sizeGuideMode(allOff())).toBe("table-and-image");
  });
});

describe("F10 phone validation", () => {
  it("accepts only +91 XXXXX XXXXX when strict", () => {
    expect(phoneValid(on("F10"), "+91 98765 43210")).toBe(true);
    expect(phoneValid(on("F10"), "9876543210")).toBe(false);
    expect(phoneValid(on("F10"), "+919876543210")).toBe(false);
  });
  it("accepts common formats when lenient but still rejects junk", () => {
    expect(phoneValid(allOff(), "9876543210")).toBe(true);
    expect(phoneValid(allOff(), "+91 98765-43210")).toBe(true);
    expect(phoneValid(allOff(), "12345")).toBe(false);
    expect(phoneValid(allOff(), 9876543210)).toBe(false);
  });
});

describe("F11 price mismatch", () => {
  const flagged = { price: 1679, price_mismatch: true, cart_price: 1879 };
  it("changes the cart price of flagged products only when on", () => {
    expect(cartUnitPrice(on("F11"), flagged)).toBe(1879);
    expect(cartUnitPrice(allOff(), flagged)).toBe(1679);
    expect(cartUnitPrice(on("F11"), { price: 999, price_mismatch: false, cart_price: null })).toBe(999);
  });
});

describe("F12 rate limit", () => {
  it("allows 20 requests per minute per key, then 429 with Retry-After", () => {
    const limiter = new RateLimiter();
    const gate = (key: string, now: number) =>
      decideGate({ path: "/c/accessories", ua: BROWSER, rateKey: key, now, toggles: on("F12") }, limiter);
    for (let i = 0; i < 20; i++) expect(gate("a", i * 100).action).toBe("allow");
    const blocked = gate("a", 2500);
    expect(blocked).toMatchObject({ action: "block", status: 429, errorCode: "RATE_LIMITED" });
    if (blocked.action === "block") expect(Number(blocked.headers["Retry-After"])).toBeGreaterThan(0);
    expect(gate("b", 2500).action).toBe("allow");
    expect(gate("a", 61_000).action).toBe("allow");
  });
  it("does not limit when off or for assets", () => {
    const limiter = new RateLimiter(1);
    for (let i = 0; i < 5; i++) {
      expect(decideGate({ path: "/", ua: BROWSER, rateKey: "a", now: i, toggles: allOff() }, limiter).action).toBe("allow");
      expect(decideGate({ path: "/_next/x.js", ua: BROWSER, rateKey: "a", now: i, toggles: on("F12") }, limiter).action).toBe("allow");
    }
  });
});

describe("F13 slow PDP", () => {
  it("adds 6-9 s on PDP paths only", () => {
    expect(pdpDelayMs(on("F13"), "/p/navy-court-sneaker", () => 0)).toBe(6000);
    expect(pdpDelayMs(on("F13"), "/p/navy-court-sneaker", () => 0.9999)).toBe(9000);
    expect(pdpDelayMs(on("F13"), "/c/accessories")).toBe(0);
    expect(pdpDelayMs(allOff(), "/p/navy-court-sneaker")).toBe(0);
  });
});

describe("F14 robots.txt", () => {
  it("disallows /p/ and /checkout for agent tokens only when on", () => {
    const body = robotsTxt(on("F14"));
    expect(body).toMatch(/User-agent: GPTBot\s+Disallow: \/p\/\s+Disallow: \/checkout/);
    expect(body).toContain("User-agent: ChatGPT-User");
    expect(robotsTxt(allOff())).not.toContain("Disallow: /p/");
  });
});

describe("F15 COD OTP", () => {
  it("only gates unverified COD orders", () => {
    expect(codOtpRequired(on("F15"), "COD", false)).toBe(true);
    expect(codOtpRequired(on("F15"), "COD", true)).toBe(false);
    expect(codOtpRequired(on("F15"), "UPI", false)).toBe(false);
    expect(codOtpRequired(allOff(), "COD", false)).toBe(false);
  });
});

describe("F16 out-of-stock dead end", () => {
  it("returns a bare 409 when on and alternatives when off", () => {
    expect(oosPolicy(on("F16"))).toEqual({ status: 409, alternatives: false });
    expect(oosPolicy(allOff())).toEqual({ status: 200, alternatives: true });
  });
});
