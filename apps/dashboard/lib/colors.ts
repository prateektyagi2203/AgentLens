/** Chart colours reference the theme tokens in app/globals.css; never put literal colours here. */
export const AGENT = "var(--agent)";
export const HUMAN = "var(--human)";
export const TIER_COLOR = {
  verified: "var(--chart-1)",
  declared: "var(--chart-5)",
  suspected: "var(--chart-4)",
  human: HUMAN,
} as const;
export const OPERATOR_COLORS = ["var(--chart-1)", "var(--chart-5)", "var(--chart-2)", "var(--chart-4)", "var(--warning)", "var(--human)"];
export const GRID = "var(--border)";
export const AXIS = "var(--muted-foreground)";
export const SUCCESS = "var(--success)";
export const DESTRUCTIVE = "var(--destructive)";
export const PRIMARY = "var(--primary)";
