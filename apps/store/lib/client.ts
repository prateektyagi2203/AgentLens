import crypto from "node:crypto";
import net from "node:net";

export interface ClientInfo {
  ip: string;
  ua: string;
  /** dt_sid from the request cookie, if any. */
  sid: string | null;
  /** Key under which server-side state (cart, pincode, otp) is kept. */
  key: string;
}

type HeaderBag = Record<string, string | string[] | undefined>;

export function headerValue(headers: HeaderBag, name: string): string | null {
  const v = headers[name];
  if (v === undefined) return null;
  const s = Array.isArray(v) ? v.join(", ") : v;
  return s === "" ? null : s;
}

/** Client IP: tunnel headers first (Cloudflare / ngrok / proxies), then the socket address. */
export function clientIp(headers: HeaderBag, socketAddr: string | undefined): string {
  const cf = headerValue(headers, "cf-connecting-ip");
  if (cf) return cf.trim();
  const xff = headerValue(headers, "x-forwarded-for");
  if (xff) return xff.split(",")[0].trim();
  return (socketAddr ?? "0.0.0.0").replace(/^::ffff:/i, "");
}

export function parseCookies(header: string | null): Record<string, string> {
  const out: Record<string, string> = {};
  if (!header) return out;
  for (const part of header.split(";")) {
    const i = part.indexOf("=");
    if (i === -1) continue;
    out[part.slice(0, i).trim()] = part.slice(i + 1).trim();
  }
  return out;
}

export const sha256 = (s: string) => crypto.createHash("sha256").update(s).digest("hex");

/** Rate-limit identity: ip+ua, deliberately independent of the (rotatable) cookie. */
export const ipUaKey = (ip: string, ua: string) => `ipua:${sha256(`${ip}|${ua}`).slice(0, 24)}`;

const SID_RE = /^[0-9a-f-]{32,40}$/i;

/** Clients without a usable dt_sid fall back to an ip+ua key so server-side friction state still works. */
export function identifyClient(headers: HeaderBag, socketAddr: string | undefined): ClientInfo {
  const ip = clientIp(headers, socketAddr);
  const ua = headerValue(headers, "user-agent") ?? "";
  const sidRaw = parseCookies(headerValue(headers, "cookie")).dt_sid;
  const sid = sidRaw && SID_RE.test(sidRaw) ? sidRaw : null;
  return { ip, ua, sid, key: sid ? `sid:${sid}` : ipUaKey(ip, ua) };
}

export function hashIp(ip: string, salt: string): string {
  return sha256(salt + ip);
}

export function hashSid(sid: string, salt: string): string {
  return sha256(salt + sid);
}

function expandV6(addr: string): string[] | null {
  const clean = addr.split("%")[0].toLowerCase();
  const [head, tail] = clean.split("::");
  const h = head ? head.split(":") : [];
  const t = tail !== undefined && tail ? tail.split(":") : [];
  if (clean.includes("::")) {
    const missing = 8 - h.length - t.length;
    if (missing < 0) return null;
    return [...h, ...Array(missing).fill("0"), ...t];
  }
  return h.length === 8 ? h : null;
}

/** /24 for IPv4, /48 for IPv6. */
export function ipPrefix(ip: string): string | null {
  const mapped = /^::ffff:(\d+\.\d+\.\d+\.\d+)$/i.exec(ip);
  const addr = mapped ? mapped[1] : ip;
  const kind = net.isIP(addr.split("%")[0]);
  if (kind === 4) {
    const [a, b, c] = addr.split(".");
    return `${a}.${b}.${c}.0/24`;
  }
  if (kind === 6) {
    const parts = expandV6(addr);
    if (!parts) return null;
    const hex = parts.slice(0, 3).map((p) => parseInt(p, 16).toString(16));
    return `${hex.join(":")}::/48`;
  }
  return null;
}
