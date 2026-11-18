# AgentLens UI Theme — handoff for Claude

Use this theme to build the complete AgentLens UI. It is a Tailwind CSS v4 theme
(CSS-first config, no `tailwind.config.js`). All colors use `oklch`.

## Design direction

- **Background:** cool white (not warm/cream)
- **Text:** near-black ink
- **Accent / primary:** blue (buttons, key labels, highlights, focus rings)
- **Neutrals:** cool greys for cards, borders, muted text
- **Fonts:** Sora for headings and UI text, JetBrains Mono for numbers, logs and code
- **Feel:** clean, editorial, product-like; generous whitespace, sharp small mono labels in uppercase with wide letter spacing

## 1. Load the fonts (in the HTML `<head>`)

```html
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link
  rel="stylesheet"
  href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Sora:wght@400;500;600;700&display=swap"
/>
```

## 2. Theme tokens (Tailwind v4 — put in your main CSS file)

```css
@import "tailwindcss";

@theme inline {
  --radius-sm: calc(var(--radius) - 4px);
  --radius-md: calc(var(--radius) - 2px);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) + 4px);
  --radius-2xl: calc(var(--radius) + 8px);

  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-destructive-foreground: var(--destructive-foreground);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);
  --color-success: var(--success);

  --font-display: var(--font-display);
  --font-mono: var(--font-mono);
}

:root {
  --radius: 0.5rem;
  --font-display: "Sora", system-ui, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, monospace;

  --background: oklch(0.985 0.003 250);      /* cool white page background */
  --foreground: oklch(0.216 0.006 56);       /* near-black ink text */
  --card: oklch(0.962 0.005 250);            /* cool light-grey cards */
  --card-foreground: oklch(0.216 0.006 56);
  --popover: oklch(0.962 0.005 250);
  --popover-foreground: oklch(0.216 0.006 56);
  --primary: oklch(0.55 0.18 255);           /* blue accent: buttons, labels, highlights */
  --primary-foreground: oklch(0.985 0.003 250);
  --secondary: oklch(0.935 0.006 250);
  --secondary-foreground: oklch(0.216 0.006 56);
  --muted: oklch(0.935 0.006 250);
  --muted-foreground: oklch(0.52 0.015 260); /* cool grey secondary text */
  --accent: oklch(0.91 0.012 250);
  --accent-foreground: oklch(0.216 0.006 56);
  --destructive: oklch(0.577 0.215 27);      /* red for errors / blockers */
  --destructive-foreground: oklch(0.985 0.003 250);
  --success: oklch(0.62 0.12 155);           /* green for fixed / healthy */
  --border: oklch(0.885 0.006 250);
  --input: oklch(0.885 0.006 250);
  --ring: oklch(0.55 0.18 255);              /* focus ring = blue */
  --grid-line: oklch(0.865 0.007 250 / 70%);
}

@layer base {
  * {
    border-color: var(--color-border);
  }
  body {
    font-family: var(--font-display);
    background-color: var(--color-background);
    color: var(--color-foreground);
  }
}

/* Optional: faint blueprint grid used behind wireframe panels */
@utility blueprint-grid {
  background-image: linear-gradient(var(--grid-line) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid-line) 1px, transparent 1px);
  background-size: calc(100% / 12) calc(100% / 8);
}
```

## 3. Usage conventions

- Buttons: `bg-primary text-primary-foreground` (blue button, white text), rounded-md, font-medium.
- Eyebrow / section labels: `font-mono text-xs uppercase tracking-widest text-primary` (small blue mono caps).
- Page headings: `font-display text-4xl md:text-5xl font-bold tracking-tight`.
- Body/secondary text: `text-muted-foreground`.
- Cards: `bg-card border border-border rounded-lg`.
- Numbers, metrics, logs, code: `font-mono`.
- Status colors: `text-destructive` for blockers/errors, `text-success` for fixed/healthy.
- Never hardcode hex colors in components — always use the semantic tokens above.

## 4. Approximate hex equivalents (for non-Tailwind contexts)

| Token | Approx hex |
|---|---|
| background (cool white) | #F8FAFC |
| foreground (ink) | #1C1917 |
| primary (blue) | #2563EB |
| muted-foreground (cool grey) | #64748B |
| border | #E2E8F0 |
| destructive (red) | #DC2626 |
| success (green) | #16A34A |
