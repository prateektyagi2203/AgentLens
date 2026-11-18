import type { AgentClass, Effort, IdentityTier, ReplayStatus, Segment, SignatureStatus } from "@/lib/types";
import { Badge, type Tone } from "./ui";

const TIER_TONE: Record<IdentityTier, Tone> = { verified: "agent", declared: "primary", suspected: "muted", human: "human" };
const TIER_HELP: Record<IdentityTier, string> = {
  verified: "Verified: the request carried a valid cryptographic signature from the agent's operator.",
  declared: "Declared: the agent identified itself in its user agent (for example ChatGPT-User). Not cryptographically proven.",
  suspected: "Suspected: inferred from behaviour (no browser beacon, fast timing...). Can be wrong.",
  human: "Human: a normal browser session.",
};
const label = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export const TierBadge = ({ tier }: { tier: IdentityTier }) => (
  <Badge tone={TIER_TONE[tier]} title={TIER_HELP[tier]}>
    {label(tier)}
  </Badge>
);

export const SegmentDot = ({ color }: { color: string }) => <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: color }} />;

export const BlockerBadge = ({ id }: { id: string }) => <Badge tone={id === "B99" ? "muted" : "destructive"}>{id}</Badge>;

const REPLAY: Record<ReplayStatus, { tone: Tone; text: string; help: string }> = {
  confirmed: { tone: "success", text: "Replay confirmed", help: "A test agent reproduced this blocker." },
  not_confirmed: { tone: "warning", text: "Not reproduced", help: "A test agent could not reproduce this blocker." },
  inconclusive: { tone: "warning", text: "Inconclusive", help: "The replay could not decide either way." },
  pending: { tone: "primary", text: "Replay running", help: "A replay is queued or running." },
  not_run: { tone: "muted", text: "No replay yet", help: "Run a replay from Settings & Report to confirm this blocker." },
};
export const ReplayBadge = ({ status }: { status: ReplayStatus }) => (
  <Badge tone={REPLAY[status].tone} title={REPLAY[status].help}>
    {status === "confirmed" ? "✓ " : ""}
    {REPLAY[status].text}
  </Badge>
);

const EFFORT: Record<Effort, string> = { S: "Small (hours)", M: "Medium (days)", L: "Large (weeks)" };
export const EffortBadge = ({ effort }: { effort: Effort }) => (
  <Badge tone="muted" title={`Effort: ${EFFORT[effort]}`}>
    {effort} · {EFFORT[effort].split(" ")[0]}
  </Badge>
);

export const StageChip = ({ stage }: { stage: string | null }) => (
  <span className="inline-flex rounded-md border border-border px-1.5 py-0.5 font-mono text-xs text-muted-foreground">{stage ?? "-"}</span>
);

export const CLASS_LABEL: Record<AgentClass | "human", string> = {
  user_fetcher: "User fetcher",
  browsing_agent: "Browsing agent",
  search_crawler: "Search crawler",
  training_crawler: "Training crawler",
  human: "Human",
};
export const SEGMENT_LABEL: Record<Segment, string> = {
  all_agents: "All agents",
  verified: "Verified",
  declared: "Declared",
  suspected: "Suspected",
  humans: "Humans",
};
export const SIGNATURE_LABEL: Record<SignatureStatus, string> = {
  valid: "Valid",
  invalid_sig: "Invalid signature",
  expired: "Expired",
  unknown_key: "Unknown key",
  fetch_failed: "Key fetch failed",
  none: "No signature",
};
