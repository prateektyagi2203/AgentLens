import { formatInr, formatPercent } from "../format";
import type { BlockerList, Overview } from "../types";

export function reportMarkdown(o: Overview, b: BlockerList): string {
  const k = o.kpis;
  const rows = b.items
    .slice(0, 8)
    .map((i) => `| ${i.blocker_id} | ${i.name} | ${i.stage} | ${i.sessions_blocked} | ${formatPercent(i.share_of_failed)} | ${formatInr(i.risk_inr.low)} - ${formatInr(i.risk_inr.high)} (base ${formatInr(i.risk_inr.base)}) |`)
    .join("\n");
  const fixes = o.top_fixes.map((f, n) => `${n + 1}. **${f.title}** (${f.blocker_id}, effort ${f.effort}) - about ${formatInr(f.risk_inr_base)} per month at risk`).join("\n");
  return `# Agent Readiness Report

Window: ${o.window.from} to ${o.window.to} (${o.window.days} days) - synthetic demo data

## Headline

- AI-agent sessions: ${k.agent_sessions.toLocaleString("en-IN")} (${formatPercent(k.agent_share)} of all sessions)
- Agent conversion: ${formatPercent(k.agent_conversion)} vs human conversion ${formatPercent(k.human_conversion)}
- Estimated monthly revenue at risk from agent blockers: ${formatInr(k.risk_inr.base)} (range ${formatInr(k.risk_inr.low)} - ${formatInr(k.risk_inr.high)})

## Top fixes

${fixes}

## Ranked blockers

| ID | Blocker | Stage | Sessions | Share of failed | Monthly risk |
|---|---|---|---|---|---|
${rows}

## Honest limitations

- Identity coverage: only Verified (cryptographically signed) and Declared (self-identifying user agent) agents are counted with confidence. Suspected agents are inferred from behaviour and can be wrong.
- Agents that disguise themselves as ordinary browsers are only partly visible.
- Revenue at risk is an estimate: sessions blocked x recoverable rate x stage probability x average order value. It is not lost revenue measured from payments.
`;
}
