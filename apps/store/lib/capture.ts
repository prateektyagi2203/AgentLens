import crypto from "node:crypto";
import type { IncomingMessage, ServerResponse } from "node:http";
import { getProductBySlug } from "./catalog";
import { identifyClient, ipUaKey } from "./client";
import { RateLimiter, decideGate, isPdpPath, readToggles } from "./friction";
import { buildRecord, logOptionsFromEnv, splitUrl, writeRecord, type RequestInfo } from "./logger";
import { aliasSid, setRequestMeta, takeRequestMeta } from "./state";

const limiter = new RateLimiter(20, 60_000);

const COOKIE_MAX_AGE = 60 * 60 * 24 * 365;

function safePath(url: string): string {
  const { path } = splitUrl(url);
  try {
    return decodeURIComponent(path);
  } catch {
    return path;
  }
}

function chunkSize(chunk: unknown, encoding: unknown): number {
  if (typeof chunk === "string") {
    return Buffer.byteLength(chunk, typeof encoding === "string" ? (encoding as BufferEncoding) : "utf8");
  }
  if (chunk instanceof Uint8Array) return chunk.byteLength;
  return 0;
}

function sleep(ms: number, res: ServerResponse): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    res.once("close", () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

/**
 * Wraps every HTTP request (pages, APIs, _next assets) of the custom server:
 * identifies the client, applies server-level friction (bot wall, rate limit, latency),
 * and writes exactly one access-log record when the response closes.
 */
export async function capture(
  req: IncomingMessage,
  res: ServerResponse,
  next: () => Promise<void> | void,
): Promise<void> {
  const startMs = Date.now();
  const t0 = performance.now();
  const requestId = crypto.randomUUID();
  const client = identifyClient(req.headers, req.socket.remoteAddress);
  const info: RequestInfo = {
    requestId,
    startMs,
    method: req.method ?? "GET",
    url: req.url ?? "/",
    headers: { ...req.headers },
    ip: client.ip,
    sid: client.sid,
  };

  // Always overwrite: clients cannot spoof the internal headers.
  req.headers["x-agentlens-request-id"] = requestId;
  req.headers["x-agentlens-client"] = client.key;
  req.headers["x-agentlens-ip"] = client.ip;

  let bytesOut = 0;
  const raw = res as unknown as Record<"write" | "end", (...args: unknown[]) => unknown>;
  for (const fn of ["write", "end"] as const) {
    const orig = raw[fn].bind(res);
    raw[fn] = (...args: unknown[]) => {
      bytesOut += chunkSize(args[0], args[1]);
      return orig(...args);
    };
  }

  if (!client.sid) {
    const newSid = crypto.randomUUID();
    // The client's earlier cookie-less state follows it once it starts sending the cookie.
    aliasSid(`sid:${newSid}`, client.key);
    const cookie = `dt_sid=${newSid}; Path=/; Max-Age=${COOKIE_MAX_AGE}; SameSite=Lax`;
    const origWriteHead = res.writeHead.bind(res) as (...args: unknown[]) => ServerResponse;
    (res as unknown as { writeHead: unknown }).writeHead = (...args: unknown[]) => {
      if (!res.headersSent) {
        const existing = res.getHeader("set-cookie");
        const list = existing == null ? [] : Array.isArray(existing) ? existing.map(String) : [String(existing)];
        res.setHeader("set-cookie", [...list, cookie]);
      }
      return origWriteHead(...args);
    };
  }

  res.once("close", () => {
    try {
      const entry = takeRequestMeta(requestId);
      const path = safePath(info.url);
      const status = res.writableFinished || res.headersSent ? res.statusCode : 499;
      const meta: Record<string, unknown> = {};
      if (info.method === "GET" && status === 200 && isPdpPath(path)) {
        const product = getProductBySlug(path.split("/")[2]);
        if (product) meta.product_id = product.id;
      }
      Object.assign(meta, entry?.meta);
      const rec = buildRecord(
        info,
        { status, bytesOut, durationMs: performance.now() - t0 },
        logOptionsFromEnv({ eventType: entry?.eventType ?? "request", meta }),
      );
      writeRecord(rec);
    } catch (err) {
      console.error("[agentlens] failed to write log record", err);
    }
  });

  try {
    const path = safePath(info.url);
    const decision = decideGate(
      { path, ua: client.ua || null, rateKey: ipUaKey(client.ip, client.ua), now: startMs, toggles: readToggles() },
      limiter,
    );
    if (decision.action === "block") {
      setRequestMeta(requestId, { meta: { error_code: decision.errorCode } });
      res.statusCode = decision.status;
      res.setHeader("Content-Type", decision.contentType);
      res.setHeader("Cache-Control", "no-store");
      for (const [k, v] of Object.entries(decision.headers)) res.setHeader(k, v);
      res.end(info.method === "HEAD" ? undefined : decision.body);
      return;
    }
    if (decision.delayMs > 0) {
      await sleep(decision.delayMs, res);
      if (res.destroyed) return;
    }
    await next();
  } catch (err) {
    console.error("[agentlens] request failed", err);
    if (!res.headersSent) {
      res.statusCode = 500;
      res.setHeader("Content-Type", "text/plain; charset=utf-8");
    }
    res.end("Internal Server Error");
  }
}
