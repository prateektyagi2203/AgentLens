# ADR-003: Dashboard is Next.js 15 with design tokens
Date: 2026-11-18
Status: Accepted
## Context
The UI style (colours, fonts) comes from a Lovable design the owner shares. No Lovable code exists to preserve.
## Decision
Build the dashboard in Next.js 15 + Tailwind (as in the PRD). All colours and fonts live in CSS variables in `apps/dashboard/app/globals.css`, so applying the Lovable theme means editing tokens only. `DEMO_MODE=1` builds a static export that reads `public/demo/*.json`.
## Consequences
Any theme change is local to one file; the public demo needs no backend.
