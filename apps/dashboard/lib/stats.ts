import type { Significance } from "./types";

/** Standard normal CDF (erf-based, |error| < 1e-7). */
export function normalCdf(z: number): number {
  const x = Math.abs(z) / Math.SQRT2;
  const t = 1 / (1 + 0.3275911 * x);
  const poly =
    ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t;
  const erf = 1 - poly * Math.exp(-x * x);
  return z >= 0 ? 0.5 * (1 + erf) : 0.5 * (1 - erf);
}

export const DEFAULT_MIN_SESSIONS = 100;

/**
 * Two-sided pooled two-proportion z-test on conversion (x converted out of n sessions).
 * Returns enough_data=false (and no z/p) if either window has fewer than `minSessions` sessions.
 */
export function twoProportionZTest(
  x1: number,
  n1: number,
  x2: number,
  n2: number,
  minSessions = DEFAULT_MIN_SESSIONS,
  alpha = 0.05,
): Significance {
  if (n1 < minSessions || n2 < minSessions) {
    return {
      test: "two_proportion_z",
      enough_data: false,
      min_sessions: minSessions,
      z: null,
      p_value: null,
      significant: false,
      note: `Not enough data: each window needs at least ${minSessions} sessions (have ${n1} and ${n2}).`,
    };
  }
  const p1 = x1 / n1;
  const p2 = x2 / n2;
  const pooled = (x1 + x2) / (n1 + n2);
  const se = Math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2));
  if (se === 0) {
    return {
      test: "two_proportion_z",
      enough_data: true,
      min_sessions: minSessions,
      z: 0,
      p_value: 1,
      significant: false,
      note: "No variation in conversion across both windows, so the test is not informative.",
    };
  }
  const z = (p2 - p1) / se;
  const p = Math.min(1, 2 * (1 - normalCdf(Math.abs(z))));
  const significant = p < alpha;
  return {
    test: "two_proportion_z",
    enough_data: true,
    min_sessions: minSessions,
    z: Number(z.toFixed(3)),
    p_value: Number(p.toPrecision(3)),
    significant,
    note: significant
      ? `The change in conversion is statistically significant (two-proportion z-test, p ${p < 0.001 ? "< 0.001" : "= " + p.toFixed(3)}).`
      : `The change is not statistically significant at the ${Math.round(alpha * 100)}% level (p = ${p.toFixed(3)}). It could be noise.`,
  };
}
