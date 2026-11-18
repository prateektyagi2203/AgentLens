const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const LAKH = 100_000;
const CRORE = 10_000_000;

function trim1(n: number): string {
  return n.toFixed(1).replace(/\.0$/, "");
}

/** ₹12.6 L, ₹1.2 Cr, and en-IN grouped rupees (₹82,400) below one lakh. */
export function formatInr(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (abs >= CRORE) return `${sign}₹${trim1(abs / CRORE)} Cr`;
  if (abs >= LAKH) {
    const lakhs = Number(trim1(abs / LAKH));
    // 99.96 L rounds up to 100 L, which reads better as 1 Cr
    if (lakhs >= 100) return `${sign}₹${trim1(abs / CRORE)} Cr`;
    return `${sign}₹${trim1(abs / LAKH)} L`;
  }
  return `${sign}₹${Math.round(abs).toLocaleString("en-IN")}`;
}

/** Exact rupees with en-IN grouping: ₹12,60,000. */
export function formatInrFull(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value < 0 ? "-" : "";
  return `${sign}₹${Math.round(Math.abs(value)).toLocaleString("en-IN")}`;
}

/** Fraction (0.31) to percent text ("31.0%"). */
export function formatPercent(fraction: number | null | undefined, digits = 1): string {
  if (fraction === null || fraction === undefined || Number.isNaN(fraction)) return "—";
  return `${(fraction * 100).toFixed(digits)}%`;
}

/** Percentage-point difference of two fractions: "+5.7 pp". */
export function formatPp(deltaFraction: number | null | undefined, digits = 1): string {
  if (deltaFraction === null || deltaFraction === undefined || Number.isNaN(deltaFraction)) return "—";
  const v = deltaFraction * 100;
  const sign = v > 0 ? "+" : v < 0 ? "-" : "";
  return `${sign}${Math.abs(v).toFixed(digits)} pp`;
}

/** Relative change as a signed percent: 0.123 -> "+12.3%". */
export function formatDeltaPercent(fraction: number | null | undefined, digits = 1): string {
  if (fraction === null || fraction === undefined || Number.isNaN(fraction)) return "—";
  const v = fraction * 100;
  const sign = v > 0 ? "+" : v < 0 ? "-" : "";
  return `${sign}${Math.abs(v).toFixed(digits)}%`;
}

/** Full integer with en-IN grouping: 1240 -> "1,240"; 1234567 -> "12,34,567". */
export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return Math.round(value).toLocaleString("en-IN");
}

/** Compact counts: 950, 12.4K, 1.2L, 3.4Cr. */
export function formatCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (abs < 1000) return `${sign}${Math.round(abs)}`;
  if (abs < LAKH) return `${sign}${trim1(abs / 1000)}K`;
  if (abs < CRORE) return `${sign}${trim1(abs / LAKH)}L`;
  return `${sign}${trim1(abs / CRORE)}Cr`;
}

/** Seconds to "4s", "1m 05s", "2h 03m". */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "—";
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total}s`;
  const m = Math.floor(total / 60);
  const s = total % 60;
  if (m < 60) return `${m}m ${String(s).padStart(2, "0")}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${String(m % 60).padStart(2, "0")}m`;
}

/** Milliseconds to "850 ms" or "1.2 s". */
export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

/** "2026-11-13" -> "13 Nov". */
export function formatDate(day: string | null | undefined): string {
  if (!day) return "—";
  const [, m, d] = day.slice(0, 10).split("-");
  const month = MONTHS[Number(m) - 1];
  if (!month) return day;
  return `${Number(d)} ${month}`;
}

export function formatDateRange(from: string, to: string): string {
  return `${formatDate(from)} – ${formatDate(to)}`;
}

/** ISO timestamp to "13 Nov, 14:05" in IST (the store's timezone). */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const d = new Date(t + IST_OFFSET_MS);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}, ${hh}:${mm}`;
}

/** ISO timestamp to "14:05:09.250" offset-style clock in IST. */
export function formatClock(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const d = new Date(t + IST_OFFSET_MS);
  const p = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`;
}

/** Day bucket (YYYY-MM-DD) of an ISO timestamp, in IST. */
export function istDay(iso: string): string {
  return new Date(Date.parse(iso) + IST_OFFSET_MS).toISOString().slice(0, 10);
}
