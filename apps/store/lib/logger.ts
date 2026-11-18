import fs from "node:fs";
import path from "node:path";
import { hashIp, hashSid, headerValue, ipPrefix } from "./client";
import { logsDir } from "./paths";
import { scrubQuery } from "./scrub";

export type EventType = "request" | "beacon" | "config_change" | "order";

/** PRD 9.2 record. Absent optional headers are logged as null. */
export interface LogRecord {
  ts: string;
  request_id: string;
  method: string;
  host: string | null;
  path: string;
  query: string;
  status: number;
  bytes_out: number;
  duration_ms: number;
  ip_hash: string;
  ip_prefix: string | null;
  user_agent: string | null;
  referer: string | null;
  accept: string | null;
  accept_language: string | null;
  sec_ch_ua: string | null;
  sec_fetch_site: string | null;
  sec_fetch_mode: string | null;
  sec_fetch_dest: string | null;
  signature: string | null;
  signature_input: string | null;
  signature_agent: string | null;
  cookie_sid_hash: string | null;
  is_asset: boolean;
  event_type: EventType;
  meta: Record<string, unknown>;
}

export const LOG_FIELDS: (keyof LogRecord)[] = [
  "ts", "request_id", "method", "host", "path", "query", "status", "bytes_out", "duration_ms",
  "ip_hash", "ip_prefix", "user_agent", "referer", "accept", "accept_language", "sec_ch_ua",
  "sec_fetch_site", "sec_fetch_mode", "sec_fetch_dest", "signature", "signature_input",
  "signature_agent", "cookie_sid_hash", "is_asset", "event_type", "meta",
];

export interface RequestInfo {
  requestId: string;
  startMs: number;
  method: string;
  /** Request target as received: path plus optional query. */
  url: string;
  headers: Record<string, string | string[] | undefined>;
  ip: string;
  sid: string | null;
}

export interface ResponseInfo {
  status: number;
  bytesOut: number;
  durationMs: number;
}

export interface LogOptions {
  salt: string;
  eventType?: EventType;
  meta?: Record<string, unknown>;
  synthMode?: boolean;
  withIpPrefix?: boolean;
}

export const envSalt = () => process.env.AGENTLENS_IP_SALT || "change-me";

const ASSET_EXT = /\.(?:js|mjs|css|map|svg|png|jpe?g|gif|webp|avif|ico|woff2?|ttf|otf)$/i;

export function isAssetPath(p: string): boolean {
  if (p.startsWith("/_next/") || p.startsWith("/img/")) return true;
  return p === "/favicon.ico" || ASSET_EXT.test(p);
}

/** "domain/path" only: no scheme, query, fragment or credentials. */
export function refererDomainPath(raw: string | null): string | null {
  if (!raw) return null;
  try {
    const u = new URL(raw);
    const p = u.pathname === "/" ? "" : u.pathname;
    return `${u.host}${p}`;
  } catch {
    return null;
  }
}

export function splitUrl(url: string): { path: string; query: string } {
  const i = url.indexOf("?");
  const rawPath = i === -1 ? url : url.slice(0, i);
  const rawQuery = i === -1 ? "" : url.slice(i + 1);
  return { path: rawPath.split("#")[0] || "/", query: rawQuery.split("#")[0] };
}

export function buildRecord(req: RequestInfo, res: ResponseInfo, opts: LogOptions): LogRecord {
  const h = req.headers;
  const { path: p, query } = splitUrl(req.url);
  const meta: Record<string, unknown> = { ...(opts.meta ?? {}) };
  if (opts.synthMode) {
    const synth = headerValue(h, "x-synth-session");
    if (synth) meta.synth_session_id = synth;
  }
  return {
    ts: new Date(req.startMs).toISOString(),
    request_id: req.requestId,
    method: req.method,
    host: headerValue(h, "host"),
    path: p,
    query: scrubQuery(query),
    status: res.status,
    bytes_out: res.bytesOut,
    duration_ms: Math.max(0, Math.round(res.durationMs)),
    ip_hash: hashIp(req.ip, opts.salt),
    ip_prefix: opts.withIpPrefix === false ? null : ipPrefix(req.ip),
    user_agent: headerValue(h, "user-agent"),
    referer: refererDomainPath(headerValue(h, "referer")),
    accept: headerValue(h, "accept"),
    accept_language: headerValue(h, "accept-language"),
    sec_ch_ua: headerValue(h, "sec-ch-ua"),
    sec_fetch_site: headerValue(h, "sec-fetch-site"),
    sec_fetch_mode: headerValue(h, "sec-fetch-mode"),
    sec_fetch_dest: headerValue(h, "sec-fetch-dest"),
    signature: headerValue(h, "signature"),
    signature_input: headerValue(h, "signature-input"),
    signature_agent: headerValue(h, "signature-agent"),
    cookie_sid_hash: req.sid ? hashSid(req.sid, opts.salt) : null,
    is_asset: isAssetPath(p),
    event_type: opts.eventType ?? "request",
    meta,
  };
}

const nginxQuote = (s: string | null) => (s ? s.replace(/"/g, "\\x22") : "-");

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function nginxTime(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getUTCDate())}/${MONTHS[d.getUTCMonth()]}/${d.getUTCFullYear()}:${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} +0000`;
}

/**
 * Nginx "combined" line plus three extra quoted fields (Signature, Signature-Input, Signature-Agent).
 * The address column holds the anonymised network address (/24 or /48 base), never the raw client IP.
 */
export function toNginxLine(rec: LogRecord): string {
  const addr = rec.ip_prefix ? rec.ip_prefix.split("/")[0] : "-";
  const target = `${rec.path}${rec.query ? `?${rec.query}` : ""}`;
  return [
    `${addr} - - [${nginxTime(rec.ts)}]`,
    `"${rec.method} ${target} HTTP/1.1"`,
    `${rec.status} ${rec.bytes_out}`,
    `"${nginxQuote(rec.referer)}" "${nginxQuote(rec.user_agent)}"`,
    `"${nginxQuote(rec.signature)}" "${nginxQuote(rec.signature_input)}" "${nginxQuote(rec.signature_agent)}"`,
  ].join(" ");
}

const ensured = new Set<string>();

function appendLine(file: string, line: string) {
  const dir = path.dirname(file);
  if (!ensured.has(dir)) {
    fs.mkdirSync(dir, { recursive: true });
    ensured.add(dir);
  }
  try {
    fs.appendFileSync(file, line + "\n");
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") {
      fs.mkdirSync(dir, { recursive: true });
      fs.appendFileSync(file, line + "\n");
    } else {
      throw err;
    }
  }
}

export function writeRecord(rec: LogRecord): void {
  const day = rec.ts.slice(0, 10);
  appendLine(path.join(logsDir(), `access-${day}.jsonl`), JSON.stringify(rec));
  if (process.env.AGENTLENS_NGINX_LOG === "1") {
    appendLine(path.join(logsDir(), "access.nginx.log"), toNginxLine(rec));
  }
}

export function logOptionsFromEnv(extra: Partial<LogOptions> = {}): LogOptions {
  return {
    salt: envSalt(),
    synthMode: process.env.AGENTLENS_SYNTH_MODE === "1",
    withIpPrefix: process.env.AGENTLENS_LOG_IP_PREFIX !== "0",
    ...extra,
  };
}
