"""HTML rendering of the Agent Readiness Report: page 1 is the shareable one-pager, page 2 the evidence and method.

The same HTML feeds the PDF (Chromium `page.pdf`) and the PNG (a screenshot of `#page1`). Fonts follow docs/theme.md
(Sora / JetBrains Mono) with system fallbacks, so the report renders the same with or without them installed.
"""

from __future__ import annotations

from html import escape
from typing import Any

from .data import VERDICT_LABEL
from .inr import inr, inr_range, pct
from .markdown import executive_summary

CSS = """
:root { --bg:#F8FAFC; --ink:#1C1917; --primary:#2563EB; --muted:#64748B; --border:#E2E8F0; --card:#F1F5F9;
        --bad:#DC2626; --good:#16A34A; --display:"Sora","Segoe UI",system-ui,-apple-system,sans-serif;
        --mono:"JetBrains Mono",ui-monospace,Consolas,"SF Mono",monospace; }
* { box-sizing:border-box; border-color:var(--border); }
@page { size:A4; margin:0; }
html,body { margin:0; background:var(--bg); color:var(--ink); font-family:var(--display); font-size:11px; line-height:1.45;
            -webkit-print-color-adjust:exact; print-color-adjust:exact; }
.page { width:210mm; height:297mm; padding:13mm 14mm; background:var(--bg); position:relative; overflow:hidden;
        page-break-after:always; break-after:page; }
.page:last-child { page-break-after:auto; break-after:auto; }
.eyebrow { font-family:var(--mono); text-transform:uppercase; letter-spacing:.14em; font-size:8.5px; color:var(--primary); }
h1 { font-size:24px; line-height:1.15; margin:3px 0 4px; font-weight:700; letter-spacing:-.01em; }
h2 { font-size:12px; margin:16px 0 6px; font-weight:600; }
h2 .eyebrow { display:block; margin-bottom:2px; }
.sub { color:var(--muted); font-size:9.5px; }
.summary { font-size:11.5px; margin:10px 0 0; padding:10px 12px; background:#fff; border:1px solid var(--border);
           border-left:3px solid var(--primary); border-radius:6px; }
.kpis { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin-top:10px; }
.kpi { background:var(--card); border:1px solid var(--border); border-radius:8px; padding:8px 10px; }
.kpi .l { font-family:var(--mono); font-size:8px; text-transform:uppercase; letter-spacing:.1em; color:var(--muted); }
.kpi .v { font-family:var(--mono); font-size:17px; font-weight:500; margin-top:2px; }
.kpi .v.bad { color:var(--bad); } .kpi .s { color:var(--muted); font-size:8.5px; }
table { width:100%; border-collapse:collapse; font-size:10px; }
th { font-family:var(--mono); font-size:8px; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); text-align:left;
     font-weight:500; padding:4px 6px; border-bottom:1px solid var(--border); }
td { padding:5px 6px; border-bottom:1px solid var(--border); vertical-align:top; }
td.n, th.n { text-align:right; font-family:var(--mono); }
.bar { height:5px; background:var(--border); border-radius:3px; margin-top:3px; }
.bar > i { display:block; height:100%; background:var(--bad); border-radius:3px; }
.bar.ag > i { background:var(--primary); } .bar.hu > i { background:var(--muted); }
.tag { font-family:var(--mono); font-size:8.5px; padding:1px 5px; border-radius:4px; border:1px solid var(--border); }
.tag.confirmed { color:var(--good); border-color:var(--good); } .tag.not_confirmed { color:var(--muted); }
.tag.inconclusive { color:#B45309; border-color:#B45309; }
.fix { padding:7px 10px; border:1px solid var(--border); border-radius:8px; background:#fff; margin-bottom:6px; }
.fix b { font-weight:600; } .fix .m { color:var(--muted); font-size:9px; }
.cols { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.ba td.good { color:var(--good); } ul { margin:4px 0 0; padding-left:15px; } li { margin-bottom:3px; }
.lim { font-size:10px; padding:9px 11px; background:#fff; border:1px solid var(--border); border-radius:6px; color:#334155; }
footer { position:absolute; left:14mm; right:14mm; bottom:9mm; display:flex; justify-content:space-between;
         font-family:var(--mono); font-size:8px; color:var(--muted); }
"""


def _e(x: Any) -> str:
    return escape(str(x), quote=True)


def _kpi(label: str, value: str, sub: str = "", bad: bool = False) -> str:
    cls = "v bad" if bad else "v"
    return f'<div class="kpi"><div class="l">{_e(label)}</div><div class="{cls}">{_e(value)}</div><div class="s">{_e(sub)}</div></div>'


def _page1(d: dict[str, Any]) -> str:
    h, w = d["headline"], d["window"]
    kpis = "".join([
        _kpi("Agent sessions", f"{h['agent_sessions']:,}", f"{pct(h['agent_share'])} of all sessions"),
        _kpi("Agent vs human conversion", f"{pct(h['agent_conversion'])} / {pct(h['human_conversion'])}", "agents / humans"),
        _kpi("Revenue at risk / month", inr(h["risk_base"]), inr_range(h["risk_low"], h["risk_high"]), bad=True),
        _kpi("Identity coverage", pct(h["identity_coverage"]), "Verified + Declared of agent sessions"),
    ])
    top_risk = max((b["risk_base"] for b in d["blockers"]), default=0) or 1
    rows = []
    for i, b in enumerate(d["blockers"], 1):
        rp = (b["replay"] or {}).get("verdict")
        tag = f'<span class="tag {_e(rp)}">{_e(VERDICT_LABEL[rp])}</span>' if rp in VERDICT_LABEL else '<span class="sub">not run</span>'
        rows.append(
            f'<tr><td class="n">{i}</td><td><b>{_e(b["name"])}</b> <span class="sub">{_e(b["blocker_id"])} / {_e(b["stage"])}'
            f'{" / low sample" if b["low_confidence"] else ""}</span>'
            f'<div class="bar"><i style="width:{max(2, round(100 * b["risk_base"] / top_risk))}%"></i></div></td>'
            f'<td class="n">{b["sessions_blocked"]:,}</td><td class="n"><b>{_e(inr(b["risk_base"]))}</b><br>'
            f'<span class="sub">{_e(inr_range(b["risk_low"], b["risk_high"]))}</span></td>'
            f'<td>{_e(b["effort"])}</td><td>{tag}</td></tr>'
        )
    blockers = (
        '<table><tr><th class="n">#</th><th>Blocker</th><th class="n">Sessions</th><th class="n">At risk / month</th>'
        f'<th>Effort</th><th>Replay</th></tr>{"".join(rows)}</table>'
        if rows else '<p class="sub">No priced blockers in this window.</p>'
    )
    fixes = "".join(
        f'<div class="fix"><b>{i}. {_e(fx["name"])}</b> <span class="m">{_e(fx["blocker_id"])} / effort {_e(fx["effort"])} / '
        f'{_e(fx["owner"])} / worth {_e(inr(fx["risk_base"]))} a month</span><div>{_e(fx["fix"])}</div>'
        f'<div class="m">Verify: {_e(fx["how_to_verify"])}</div></div>'
        for i, fx in enumerate(d["fixes"], 1)
    ) or '<p class="sub">No recommendations: no priced blockers.</p>'
    return f"""
<section class="page" id="page1">
  <div class="eyebrow">Agent Readiness Report</div>
  <h1>Are AI shopping agents able to buy from this store?</h1>
  <div class="sub">Data window {_e(w["from"])} to {_e(w["to"])} ({w["days"]} days) &middot; {_e(d["segment_label"])} &middot; generated {_e(d["generated_at"])}</div>
  <div class="summary">{_e(executive_summary(d))}</div>
  <div class="kpis">{kpis}</div>
  <h2><span class="eyebrow">Where agents get stuck</span>Top blockers</h2>
  {blockers}
  <h2><span class="eyebrow">What to do first</span>Top fixes</h2>
  {fixes}
  <h2><span class="eyebrow">Result</span>Before and after</h2>
  {_before_after(d)}
  <footer><span>AgentLens &middot; estimates per 30 days, in INR</span><span>1 / 2</span></footer>
</section>"""


def _funnel_rows(d: dict[str, Any]) -> str:
    out = []
    for a, hu in zip(d["funnel"]["agents"]["steps"], d["funnel"]["humans"]["steps"], strict=False):
        out.append(
            f'<tr><td>{_e(a["stage_id"])} {_e(a["name"])}</td>'
            f'<td class="n">{a["sessions"]:,}<div class="bar ag"><i style="width:{round(100 * a["overall_conversion"])}%"></i></div></td>'
            f'<td class="n">{pct(a["overall_conversion"])}</td>'
            f'<td class="n">{hu["sessions"]:,}<div class="bar hu"><i style="width:{round(100 * hu["overall_conversion"])}%"></i></div></td>'
            f'<td class="n">{pct(hu["overall_conversion"])}</td></tr>'
        )
    return "".join(out)


def _replays(d: dict[str, Any]) -> str:
    if not d["replays"]:
        return '<p class="sub">No replays run yet (agentlens replay-all).</p>'
    rows = "".join(
        f'<tr><td>{_e(r["blocker_id"])}</td><td><span class="tag {_e(r["verdict"])}">{_e(VERDICT_LABEL.get(r["verdict"], r["verdict"]))}</span></td>'
        f'<td>{_e(r["mode"])}</td><td>{_e((r["explanation"] or "")[:170])}</td></tr>'
        for r in d["replays"][:8]
    )
    return f"<table><tr><th>Blocker</th><th>Verdict</th><th>Mode</th><th>What happened</th></tr>{rows}</table>"


def _before_after(d: dict[str, Any]) -> str:
    ba = d.get("before_after")
    if not ba:
        return '<p class="sub">No before/after comparison yet: record a fix, let new traffic arrive, regenerate.</p>'
    x, cmp = ba["headline"], ba["compare"]
    return f"""<table class="ba"><tr><th>Metric</th><th class="n">Before</th><th class="n">After</th></tr>
<tr><td>Agent sessions</td><td class="n">{x["sessions_before"]:,}</td><td class="n">{x["sessions_after"]:,}</td></tr>
<tr><td>Agent conversion</td><td class="n">{pct(x["conversion_before"])}</td><td class="n good">{pct(x["conversion_after"])}</td></tr>
<tr><td>Agent revenue</td><td class="n">{_e(inr(x["agent_revenue_before_inr"]))}</td><td class="n good">{_e(inr(x["agent_revenue_after_inr"]))}</td></tr>
<tr><td>At risk / month</td><td class="n">{_e(inr(x["risk_before_inr"]))}</td><td class="n good">{_e(inr(x["risk_after_inr"]))}</td></tr></table>
<p class="sub">{_e(ba["label"])}. {_e(cmp["significance"]["note"])}</p>"""


def _page2(d: dict[str, Any]) -> str:
    a = d["assumptions"]
    rr = a["recoverable_rate"]
    return f"""
<section class="page" id="page2">
  <div class="eyebrow">Evidence and method</div>
  <h1>How the numbers were built</h1>
  <h2><span class="eyebrow">Funnel</span>Agents vs humans</h2>
  <table><tr><th>Stage</th><th class="n">Agents reaching</th><th class="n">% of S1</th><th class="n">Humans reaching</th><th class="n">% of S1</th></tr>
  {_funnel_rows(d)}</table>
  <h2><span class="eyebrow">Replay agent</span>Hypotheses checked</h2>{_replays(d)}
  <h2><span class="eyebrow">Method</span>Assumptions</h2>
  <ul>
    <li>Agents are identified from access logs: Verified (Web Bot Auth signature), Declared (known user-agent), Suspected (behaviour).</li>
    <li>Each failed agent session gets one terminal blocker from deterministic rules; unmatched sessions are Unknown and never priced.</li>
    <li>At risk = blocked sessions &times; recoverable rate ({rr["low"]} / {rr["base"]} / {rr["high"]}) &times; probability of buying
        &times; AOV ({_e(inr(a["aov_inr"]))}) &times; {a["scale_k"]} (scales {a["window_days"]} days to 30).</li>
    <li>Replays confirm a hypothesis on a test store; they do not prove the same blocker hit a specific real session.</li>
  </ul>
  <h2><span class="eyebrow">Read this first</span>Honest limitations</h2>
  <div class="lim">{_e(d["limitation"])}</div>
  <footer><span>AgentLens &middot; estimates, not forecasts</span><span>2 / 2</span></footer>
</section>"""


def render_html(d: dict[str, Any]) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Agent Readiness Report</title>'
        f"<style>{CSS}</style></head><body>{_page1(d)}{_page2(d)}</body></html>"
    )
