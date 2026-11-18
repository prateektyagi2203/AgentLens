# ADR-007: Diagnosis and impact methodology
Date: 2026-11-20
Status: Accepted
## Context
M3 must say why an agent session failed, price it in rupees and rank fixes (PRD 12-15), while meeting SC4 (precision >= 0.85, recall >= 0.80, rules-only) and staying explainable. The pipeline must run with no key and no network, and diagnosis code must never see synthetic ground truth.
## Decision
- **Rules first.** Each blocker B01-B16 is a deterministic SQL rule over the session's requests (`status`, `error_code`, path, timing, catalog price/stock) plus point-in-time site checks. Rules are set-based, so 1M log lines diagnose in seconds. Every hit stores evidence (request ids, site-check results) in `blocker_hits.evidence_json`.
- **One terminal blocker per session.** Highest confidence is not enough, since a failed early step can be followed by a deeper one: the deepest funnel stage wins, then the latest evidence, then confidence. Hits under 0.5 never become terminal (content rules abstain without site checks). This is what prevents double counting in impact.
- **Site checks are time-valid.** Each check applies from its run until the next one, so a before/after fix is judged against the store as it was. With no URL or an unreachable store the probe records `skipped` and diagnosis degrades to logs only.
- **LLM only for the unexplained (B99 candidates)**, behind the ADR-001 provider interface: `mock` default (deterministic), `openai` when `OPENAI_API_KEY` is set. Inputs are redacted, capped per run, cached; verdicts under 0.6 are discarded. Rules-only mode is the supported baseline and the one SC4 measures.
- **Impact = L x r x p_s x AOV x k** (PRD 14.1), with low/base/high bands (r 0.4/0.6/0.8, p_s +-20%). Sessions are counted once, by terminal blocker. Extension to the PRD: when too few agent sessions (< 30, or < 5 conversions) reached the stage to estimate p_s, it falls back to the human conversion at that stage, and the choice is stored in `impact_assumptions` so the UI can flag it. Crawlers, humans and B99 carry no rupees.
- **Priority = risk_base / effort weight** (S1, M2, L4), recommendations keyed `rec-<blocker>` so user status survives re-runs.
- **Evaluation** lives only in `agentlens.eval`: a 2,000-session deterministic golden set from eight synth segments, scored per blocker. Ambiguity that logs cannot resolve (B04 vs a normal PDP read) is allowed to cost precision; abstaining is never a false positive.
## Alternatives considered
- LLM-first classification: not reproducible, costs money, needs network; rejected for the main path.
- Highest-confidence-wins terminal selection: misattributes sessions that fail twice.
- Splitting a session's rupees across overlapping blockers: no principled weights; one-terminal rule is simpler and auditable.
## Consequences
- Rules need explicit thresholds (`config/diagnosis.yaml`) and per-rule tests; adding a blocker is a rule + yaml entry (see `docs/diagnosis.md`).
- B07 (overlay) cannot be confirmed from logs alone and stays at 0.5-0.6 until a replay confirms it.
- B03/B04/B09 need site checks to be confident; without them they abstain instead of guessing.
- The synth generator gained an optional `noise.p_broken_link` (default 0, existing seeds unchanged) so B16 can be evaluated.
