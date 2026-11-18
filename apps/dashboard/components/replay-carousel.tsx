"use client";

import { useState } from "react";
import { assetUrl } from "@/lib/api";
import type { ReplayStep } from "@/lib/types";
import { Badge, Button } from "./ui";

/** Step-by-step screenshot carousel. Fetch-mode replays have no screenshots, so the steps render as a text list. */
export function ReplayCarousel({ steps, title }: { steps: ReplayStep[]; title: string }) {
  const [i, setI] = useState(0);
  const withShots = steps.filter((s) => s.screenshot_url);
  if (!steps.length) return null;
  if (!withShots.length) {
    return (
      <ol className="space-y-2" aria-label={title}>
        {steps.map((s) => (
          <li key={s.n} className="rounded-md border border-border p-3 text-sm">
            <span className="font-mono text-xs text-primary">STEP {s.n}</span> {s.action}
            <p className="mt-1 text-xs text-muted-foreground">{s.note}</p>
          </li>
        ))}
        <li className="text-xs text-muted-foreground">Fetch-mode replay: no screenshots are taken.</li>
      </ol>
    );
  }
  const step = withShots[Math.min(i, withShots.length - 1)];
  const src = assetUrl(step.screenshot_url);
  const failed = step.status !== null && step.status >= 400;
  return (
    <div data-testid="replay-carousel" role="group" aria-roledescription="carousel" aria-label={title}>
      <div className="overflow-hidden rounded-lg border border-border bg-background">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={src ?? ""} alt={`Step ${step.n}: ${step.action}`} className="aspect-[16/10] w-full object-cover object-top" />
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="font-mono text-xs uppercase tracking-widest text-primary">
            Step {step.n} of {steps.length}
          </p>
          <p className="mt-1 text-sm font-medium">{step.action}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">{step.note}</p>
        </div>
        <div className="flex items-center gap-2">
          {step.status !== null && <Badge tone={failed ? "destructive" : "success"}>{step.method} {step.status}</Badge>}
          <Button variant="secondary" aria-label="Previous step" disabled={i === 0} onClick={() => setI(i - 1)}>←</Button>
          <Button variant="secondary" aria-label="Next step" disabled={i >= withShots.length - 1} onClick={() => setI(i + 1)}>→</Button>
        </div>
      </div>
    </div>
  );
}
