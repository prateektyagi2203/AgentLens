"""Markdown rendering of the Agent Readiness Report (also the source of the executive summary text)."""

from __future__ import annotations

from typing import Any

from .data import SEGMENT_LABEL, VERDICT_LABEL
from .inr import inr, inr_full, inr_range, pct


def _n(x: float | int) -> str:
    return f"{int(x):,}"


def executive_summary(d: dict[str, Any]) -> str:
    h = d["headline"]
    w = d["window"]
    if not d["has_data"]:
        return "No sessions were found for the selected window and filters, so there is nothing to report yet."
    seg = SEGMENT_LABEL.get(d["segment"], d["segment"])
    parts = [
        f"Between {w['from']} and {w['to']} ({w['days']} days), {seg} generated {_n(h['agent_sessions'])} of "
        f"{_n(h['total_sessions'])} sessions ({pct(h['agent_share'])}). Agents converted at {pct(h['agent_conversion'])} "
        f"against {pct(h['human_conversion'])} for human visitors."
    ]
    if d["blockers"]:
        top = d["blockers"][0]
        parts.append(
            f"The biggest blocker is {top['name']} ({top['blocker_id']}): it ended {_n(top['sessions_blocked'])} agent sessions "
            f"({pct(top['share_of_failed'], 0)} of failed ones). Across all blockers AgentLens estimates {inr(h['risk_base'])} "
            f"of agent revenue at risk per month (range {inr_range(h['risk_low'], h['risk_high'])})."
        )
    else:
        parts.append("No priced blockers were found in this window.")
    ba = d.get("before_after")
    if ba:
        x = ba["headline"]
        parts.append(
            f"After the change \"{ba['label'].removeprefix('Around ').strip(chr(34))}\", agent conversion moved from "
            f"{pct(x['conversion_before'])} to {pct(x['conversion_after'])} and estimated risk fell from "
            f"{inr(x['risk_before_inr'])} to {inr(x['risk_after_inr'])} per month."
        )
    return " ".join(parts)


def render_markdown(d: dict[str, Any]) -> str:
    h, w = d["headline"], d["window"]
    L: list[str] = []
    add = L.append
    add("# Agent Readiness Report")
    add("")
    filt = f"segment: {d['segment_label']}"
    if d.get("operator"):
        filt += f", operator: {d['operator']}"
    if d.get("agent_class"):
        filt += f", class: {d['agent_class']}"
    add(f"*Data window {w['from']} to {w['to']} ({w['days']} days). Filters: {filt}. Generated {d['generated_at']}. "
        f"All money in INR; figures are estimates per 30 days.*")
    add("")
    add("## Executive summary")
    add("")
    add(executive_summary(d))
    add("")
    add("## Headline numbers")
    add("")
    add("| Metric | Value |")
    add("|---|---|")
    add(f"| Agent sessions | {_n(h['agent_sessions'])} ({pct(h['agent_share'])} of {_n(h['total_sessions'])} sessions) |")
    add(f"| Agent conversion | {pct(h['agent_conversion'])} ({_n(h['agent_converted'])} orders) |")
    add(f"| Human conversion | {pct(h['human_conversion'])} |")
    add(f"| Agent revenue in window | {inr(h['agent_revenue'])} ({inr_full(h['agent_revenue'])}) |")
    add(f"| Revenue at risk per month | **{inr(h['risk_base'])}** (range {inr_range(h['risk_low'], h['risk_high'])}) |")
    add(f"| Identity coverage | {pct(h['identity_coverage'])} (Verified {_n(h['tiers']['verified'])}, "
        f"Declared {_n(h['tiers']['declared'])}, Suspected {_n(h['tiers']['suspected'])}) |")
    add(f"| Failed agent sessions diagnosed | {pct(h['diagnosed_share'], 0)} (unknown cause: {pct(h['unknown_share'], 0)}) |")
    add("")
    add("## Agent vs human funnel")
    add("")
    add("| Stage | Agents reaching | Agents % of S1 | Humans reaching | Humans % of S1 |")
    add("|---|---:|---:|---:|---:|")
    for a, hu in zip(d["funnel"]["agents"]["steps"], d["funnel"]["humans"]["steps"], strict=False):
        add(f"| {a['stage_id']} {a['name']} | {_n(a['sessions'])} | {pct(a['overall_conversion'])} | "
            f"{_n(hu['sessions'])} | {pct(hu['overall_conversion'])} |")
    add("")
    add("## Top blockers")
    add("")
    if d["blockers"]:
        add("| # | Blocker | Stage | Agent sessions | Revenue at risk / month (base, range) | Effort | Replay |")
        add("|---:|---|---|---:|---|---|---|")
        for i, b in enumerate(d["blockers"], 1):
            rp = VERDICT_LABEL.get((b["replay"] or {}).get("verdict", ""), "Not run")
            low = " (low sample)" if b["low_confidence"] else ""
            add(f"| {i} | {b['blocker_id']} {b['name']}{low} | {b['stage']} {b['stage_name']} | {_n(b['sessions_blocked'])} | "
                f"**{inr(b['risk_base'])}** ({inr_range(b['risk_low'], b['risk_high'])}) | {b['effort']} | {rp} |")
    else:
        add("No priced blockers in this window.")
    add("")
    add("## Recommendations")
    add("")
    if d["fixes"]:
        for i, fx in enumerate(d["fixes"], 1):
            add(f"{i}. **{fx['name']}** ({fx['blocker_id']}, effort {fx['effort']}, owner {fx['owner']}): {fx['fix']}")
            add(f"   - Worth about {inr(fx['risk_base'])} per month.")
            add(f"   - How to verify: {fx['how_to_verify']}")
            if fx["explanation"]:
                add(f"   - Why: {fx['explanation']}")
    else:
        add("No recommendations: no priced blockers.")
    add("")
    add("## Replay evidence")
    add("")
    if d["replays"]:
        add("A replay agent re-ran the shopping task against the test store to check each hypothesis "
            "(identified as AgentLens-Replay, test data only).")
        add("")
        add("| Blocker | Verdict | Mode | Steps | When | What happened |")
        add("|---|---|---|---:|---|---|")
        for r in d["replays"]:
            expl = (r["explanation"] or "").replace("|", "/").replace("\n", " ")
            add(f"| {r['blocker_id']} | {VERDICT_LABEL.get(r['verdict'], r['verdict'])} | {r['mode']} | {r['steps']} | "
                f"{r['started_at'] or ''} | {expl} |")
    else:
        add("No replays have been run yet. Run `agentlens replay-all` to verify the top blockers against a test store.")
    add("")
    add("## Before and after")
    add("")
    ba = d.get("before_after")
    if ba:
        x = ba["headline"]
        cmp = ba["compare"]
        add(f"Comparison: {ba['label']} ({cmp['a']['window']['from']} to {cmp['a']['window']['to']} vs "
            f"{cmp['b']['window']['from']} to {cmp['b']['window']['to']}).")
        add("")
        add("| Metric | Before | After |")
        add("|---|---:|---:|")
        add(f"| Agent sessions | {_n(x['sessions_before'])} | {_n(x['sessions_after'])} |")
        add(f"| Agent conversion | {pct(x['conversion_before'])} | {pct(x['conversion_after'])} |")
        add(f"| Agent revenue | {inr(x['agent_revenue_before_inr'])} | {inr(x['agent_revenue_after_inr'])} |")
        add(f"| Revenue at risk / month | {inr(x['risk_before_inr'])} | {inr(x['risk_after_inr'])} |")
        add("")
        add(cmp["significance"]["note"])
        moved = [r for r in ba["blocker_deltas"] if r["risk_before_inr"] != r["risk_after_inr"]][:4]
        if moved:
            add("")
            add("Biggest changes by blocker: " + "; ".join(
                f"{r['blocker_id']} {inr(r['risk_before_inr'])} to {inr(r['risk_after_inr'])}" for r in moved) + ".")
    else:
        add("No before/after comparison yet: mark a recommendation as fixed (or record a config change) and let new "
            "traffic arrive, then regenerate this report.")
    add("")
    add("## Methodology and assumptions")
    add("")
    a = d["assumptions"]
    rr = a["recoverable_rate"]
    add("- Agents are identified from access logs: Verified (Web Bot Auth signature), Declared (known user-agent), "
        "Suspected (behavioural score). Humans are everything else.")
    add("- Each failed agent session is assigned one terminal blocker by deterministic rules over its requests; "
        "sessions with no matching rule are reported as Unknown and never priced.")
    add(f"- Revenue at risk = blocked sessions x recoverable rate (low {rr['low']}, base {rr['base']}, high {rr['high']}) x "
        f"probability the session would have bought x average order value ({inr_full(a['aov_inr'])}) x {a['scale_k']} "
        f"(scales {a['window_days']} days to 30).")
    add(f"- The probability uses agent conversion past the blocking stage, falling back to human conversion where agent "
        f"samples are thin (fewer than {a['min_sample']} sessions are flagged low sample). The band on it is "
        f"+/-{round(a['p_stage_band'] * 100)}%.")
    add("- Replays confirm a hypothesis on a test store; they do not prove the same blocker affected a specific real session.")
    add("")
    add("## Honest limitations")
    add("")
    add(d["limitation"])
    add("")
    return "\n".join(L)
