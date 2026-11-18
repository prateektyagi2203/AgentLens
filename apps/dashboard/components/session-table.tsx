"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ColumnDef } from "@tanstack/react-table";
import { formatDateTime, formatDuration, formatInr } from "@/lib/format";
import { useFilters } from "@/lib/hooks";
import type { SessionRow } from "@/lib/types";
import { DataTable } from "./data-table";
import { BlockerBadge, StageChip, TierBadge } from "./domain";
import { Badge } from "./ui";

/** Shared sessions table; rows open the timeline view at /sessions?id=. */
export function SessionTable({ rows, compact = false, caption = "Sessions" }: { rows: SessionRow[]; compact?: boolean; caption?: string }) {
  const router = useRouter();
  const { href } = useFilters();
  const columns: ColumnDef<SessionRow>[] = [
    { id: "id", header: "Session", accessorFn: (s) => s.session_id, cell: ({ row }) => <Link href={href("/sessions", { id: row.original.session_id })} className="font-mono text-xs text-primary hover:underline" onClick={(e) => e.stopPropagation()}>{row.original.session_id}</Link> },
    { id: "when", header: "Started", accessorFn: (s) => s.start_ts, cell: ({ row }) => <span className="font-mono text-xs">{formatDateTime(row.original.start_ts)}</span> },
    { id: "agent", header: "Agent", accessorFn: (s) => s.agent_name, cell: ({ row }) => <span>{row.original.agent_name}</span> },
    { id: "tier", header: "Identity", accessorFn: (s) => s.identity_tier, cell: ({ row }) => <TierBadge tier={row.original.identity_tier} /> },
    { id: "stage", header: "Furthest", accessorFn: (s) => s.max_stage ?? "", cell: ({ row }) => <StageChip stage={row.original.max_stage} /> },
    { id: "outcome", header: "Outcome", accessorFn: (s) => (s.converted ? 1 : 0), cell: ({ row }) => row.original.converted ? <Badge tone="success">Purchased {formatInr(row.original.order_value_inr)}</Badge> : row.original.terminal_blocker_id ? <span className="flex items-center gap-2"><BlockerBadge id={row.original.terminal_blocker_id} /><span className="text-xs text-muted-foreground">{row.original.terminal_blocker_name}</span></span> : <Badge tone="muted">Abandoned</Badge> },
    { id: "dur", header: "Duration", accessorFn: (s) => s.duration_s, cell: ({ row }) => <span className="font-mono text-xs">{formatDuration(row.original.duration_s)}</span> },
  ];
  const visible = compact ? columns.filter((c) => ["id", "agent", "outcome"].includes(c.id ?? "")) : columns;
  return <DataTable caption={caption} data={rows} columns={visible} getRowId={(s) => s.session_id} onRowClick={(s) => router.push(href("/sessions", { id: s.session_id }))} />;
}
