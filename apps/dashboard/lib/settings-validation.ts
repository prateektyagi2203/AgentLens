import type { Settings } from "./types";

type Errors = Record<string, string>;

const num = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

function range(errors: Errors, key: string, v: unknown, min: number, max: number, opts: { int?: boolean } = {}) {
  if (!num(v)) errors[key] = "Enter a number";
  else if (opts.int && !Number.isInteger(v)) errors[key] = "Must be a whole number";
  else if (v < min || v > max) errors[key] = `Must be between ${min} and ${max}`;
}

/**
 * Field-level validation shared by the Settings form and the mock `PUT /settings`.
 * The backend must enforce the same rules (docs/api-contract.md, "Settings validation").
 * Keys are dotted paths into the Settings object.
 */
export function validateSettings(s: Settings): Errors {
  const e: Errors = {};
  const { impact, identification: id, thresholds } = s;

  range(e, "impact.recoverable_rate.low", impact.recoverable_rate.low, 0, 1);
  range(e, "impact.recoverable_rate.base", impact.recoverable_rate.base, 0, 1);
  range(e, "impact.recoverable_rate.high", impact.recoverable_rate.high, 0, 1);
  if (!e["impact.recoverable_rate.low"] && !e["impact.recoverable_rate.base"] && impact.recoverable_rate.low > impact.recoverable_rate.base)
    e["impact.recoverable_rate.low"] = "Low must not exceed base";
  if (!e["impact.recoverable_rate.base"] && !e["impact.recoverable_rate.high"] && impact.recoverable_rate.base > impact.recoverable_rate.high)
    e["impact.recoverable_rate.high"] = "High must not be below base";
  range(e, "impact.p_stage_band", impact.p_stage_band, 0, 0.9);
  range(e, "impact.default_aov_inr", impact.default_aov_inr, 1, 10_000_000);
  range(e, "impact.agent_vs_human_factor", impact.agent_vs_human_factor, 0.1, 5);
  range(e, "impact.min_sample", impact.min_sample, 1, 100_000, { int: true });
  for (const k of ["S", "M", "L"] as const) range(e, `impact.effort_weights.${k}`, impact.effort_weights[k], 0.5, 100);
  if (!e["impact.effort_weights.S"] && !e["impact.effort_weights.M"] && impact.effort_weights.S > impact.effort_weights.M)
    e["impact.effort_weights.M"] = "M must be at least S";
  if (!e["impact.effort_weights.M"] && !e["impact.effort_weights.L"] && impact.effort_weights.M > impact.effort_weights.L)
    e["impact.effort_weights.L"] = "L must be at least M";

  range(e, "identification.signature.clock_skew_s", id.signature.clock_skew_s, 0, 600, { int: true });
  range(e, "identification.signature.key_cache_ttl_s", id.signature.key_cache_ttl_s, 60, 86_400, { int: true });
  range(e, "identification.suspicion.threshold", id.suspicion.threshold, 1, 100);
  range(e, "identification.suspicion.page_velocity_per_min", id.suspicion.page_velocity_per_min, 1, 600);
  for (const [k, v] of Object.entries(id.suspicion.weights)) range(e, `identification.suspicion.weights.${k}`, v, 0, 100);
  range(e, "identification.sessions.timeout_min_human", id.sessions.timeout_min_human, 1, 240, { int: true });
  range(e, "identification.sessions.timeout_min_agent", id.sessions.timeout_min_agent, 1, 240, { int: true });

  range(e, "thresholds.slow_response_ms", thresholds.slow_response_ms, 100, 60_000, { int: true });
  range(e, "thresholds.significance_min_sessions", thresholds.significance_min_sessions, 10, 100_000, { int: true });
  return e;
}
