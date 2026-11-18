/**
 * The ONE place that decides where dashboard data comes from.
 *   api   (default)                      -> FastAPI at NEXT_PUBLIC_API_URL
 *   mocks (NEXT_PUBLIC_USE_MOCKS=1)      -> in-browser fixtures (lib/fixtures), writes work in-memory
 *   demo  (NEXT_PUBLIC_DEMO_MODE=1 or DEMO_MODE=1) -> static snapshots under /demo/*.json (read-only)
 * Never falls back to mocks when the API is unreachable: the UI shows an error state instead.
 * next.config.mjs maps DEMO_MODE to NEXT_PUBLIC_DEMO_MODE so both spellings work.
 */
export type DataMode = "api" | "mocks" | "demo";

const flag = (v: string | undefined) => v === "1" || v === "true";

export const MODE: DataMode = flag(process.env.NEXT_PUBLIC_DEMO_MODE)
  ? "demo"
  : flag(process.env.NEXT_PUBLIC_USE_MOCKS)
    ? "mocks"
    : "api";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8100/api").replace(/\/+$/, "");
export const API_ORIGIN = API_URL.replace(/\/api$/, "");
export const DEMO_BASE = "/demo";

export const IS_DEMO = MODE === "demo";
export const IS_MOCK = MODE === "mocks";
/** Writes (PATCH/PUT/POST) work against the API and the in-memory mocks, never against static snapshots. */
export const CAN_WRITE = MODE !== "demo";
