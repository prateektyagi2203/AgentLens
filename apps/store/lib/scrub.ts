const PII_KEY = /(phone|mobile|msisdn|e-?mail|otp|passw|address|contact|captcha|cvv|card|upi)/i;
const EMAIL_VALUE = /[^\s@]+@[^\s@]+/;
// 10 or more digits (optionally separated), i.e. a phone-number-like value; 6-digit pincodes stay visible.
const PHONE_VALUE = /(?:\d[\s\-.]?){10,}/;

export const REDACTED = "REDACTED";

function safeDecode(s: string): string {
  try {
    return decodeURIComponent(s.replace(/\+/g, " "));
  } catch {
    return s;
  }
}

/** Redacts values that look like phone/email/OTP or sit under PII-ish keys. Keeps key order and non-PII pairs verbatim. */
export function scrubQuery(raw: string | null | undefined): string {
  if (!raw) return "";
  const query = raw.startsWith("?") ? raw.slice(1) : raw;
  if (!query) return "";
  return query
    .split("&")
    .filter((pair) => pair.length > 0)
    .map((pair) => {
      const eq = pair.indexOf("=");
      if (eq === -1) {
        const decoded = safeDecode(pair);
        return EMAIL_VALUE.test(decoded) || PHONE_VALUE.test(decoded) ? REDACTED : pair;
      }
      const key = pair.slice(0, eq);
      const value = safeDecode(pair.slice(eq + 1));
      const redact = PII_KEY.test(safeDecode(key)) || EMAIL_VALUE.test(value) || PHONE_VALUE.test(value);
      return redact ? `${key}=${REDACTED}` : pair;
    })
    .join("&");
}
