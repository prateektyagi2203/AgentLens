import crypto from "node:crypto";
import { NextResponse } from "next/server";
import { identifyClient } from "./client";
import { buildRecord, logOptionsFromEnv, writeRecord, type EventType } from "./logger";
import { getState, setRequestMeta, type ClientState } from "./state";

export interface ApiContext {
  requestId: string | null;
  clientKey: string;
  state: ClientState;
}

export function apiContext(req: Request): ApiContext {
  const clientKey = req.headers.get("x-agentlens-client") ?? "anon";
  return { requestId: req.headers.get("x-agentlens-request-id"), clientKey, state: getState(clientKey) };
}

/** JSON response; `meta` is handed to the access logger (generic API signals only). */
export function jsonResponse(
  req: Request,
  status: number,
  body: unknown,
  meta?: Record<string, unknown>,
  headers?: Record<string, string>,
): NextResponse {
  setRequestMeta(req.headers.get("x-agentlens-request-id"), { meta });
  return NextResponse.json(body, { status, headers: { "Cache-Control": "no-store", ...headers } });
}

export function apiError(
  req: Request,
  status: number,
  errorCode: string,
  extra: Record<string, unknown> = {},
  headers?: Record<string, string>,
): NextResponse {
  return jsonResponse(req, status, { error_code: errorCode, ...extra }, { error_code: errorCode }, headers);
}

export async function readJson(req: Request): Promise<Record<string, unknown>> {
  try {
    const body = await req.json();
    return body && typeof body === "object" && !Array.isArray(body) ? (body as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

export const str = (v: unknown): string => (typeof v === "string" ? v : "");

/** Writes an additional access-log line (order / config_change) attributed to the current request. */
export function logExtraEvent(req: Request, eventType: EventType, meta: Record<string, unknown>, status: number): void {
  const url = new URL(req.url);
  const headers = Object.fromEntries(req.headers.entries());
  const client = identifyClient(headers, undefined);
  const rec = buildRecord(
    {
      requestId: crypto.randomUUID(),
      startMs: Date.now(),
      method: req.method,
      url: url.pathname + url.search,
      headers,
      ip: headers["x-agentlens-ip"] ?? "0.0.0.0",
      sid: client.sid,
    },
    { status, bytesOut: 0, durationMs: 0 },
    logOptionsFromEnv({ eventType, meta }),
  );
  writeRecord(rec);
}
