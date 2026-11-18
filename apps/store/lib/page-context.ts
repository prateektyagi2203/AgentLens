import { headers } from "next/headers";
import { getState } from "./state";

/** Server-component access to the per-client state and the request origin. */
export async function pageContext() {
  const h = await headers();
  const key = h.get("x-agentlens-client") ?? "anon";
  const host = h.get("host") ?? "localhost:3100";
  const proto = h.get("x-forwarded-proto") ?? "http";
  return { state: getState(key), origin: `${proto}://${host}` };
}
