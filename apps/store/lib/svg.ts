import type { CategorySlug, Product } from "./catalog";

const COLOUR_HEX: Record<string, string> = {
  white: "#f3f1ec", black: "#2b2b2b", navy: "#24304f", olive: "#6f7b3d", maroon: "#7d2231", mustard: "#d8a620",
  teal: "#21807f", pink: "#e592a8", indigo: "#3b3f8c", grey: "#9a9ea6", tan: "#b8855a", "sky blue": "#7fb7e0",
};

export const hexFor = (colour: string) => COLOUR_HEX[colour.toLowerCase()] ?? "#c9b8a6";

function shade(hex: string, amt: number): string {
  const n = parseInt(hex.slice(1), 16);
  const ch = (v: number) => Math.max(0, Math.min(255, v + amt));
  const r = ch((n >> 16) & 255);
  const g = ch((n >> 8) & 255);
  const b = ch(n & 255);
  return `#${((1 << 24) | (r << 16) | (g << 8) | b).toString(16).slice(1)}`;
}

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function shape(category: CategorySlug, fill: string, accent: string, isBelt: boolean): string {
  switch (category) {
    case "mens-sneakers":
      return `<path d="M120 420 C150 300 230 280 290 330 L330 380 C390 390 450 400 490 440 L490 470 L120 470 Z" fill="${fill}"/>
<rect x="110" y="466" width="390" height="30" rx="15" fill="${accent}"/>
<path d="M300 340 l25 25 M270 355 l25 25 M240 370 l25 25" stroke="${accent}" stroke-width="6" stroke-linecap="round"/>`;
    case "womens-kurtas":
      return `<path d="M230 130 L300 160 L370 130 L450 200 L410 260 L400 560 L200 560 L190 260 L150 200 Z" fill="${fill}"/>
<path d="M300 160 L300 330" stroke="${accent}" stroke-width="5"/>
<path d="M200 520 H400 M205 540 H395" stroke="${accent}" stroke-width="6"/>`;
    case "mens-shirts":
      return `<path d="M220 140 L300 175 L380 140 L470 210 L430 270 L405 250 L405 570 L195 570 L195 250 L170 270 L130 210 Z" fill="${fill}"/>
<path d="M220 140 L300 230 L380 140" fill="none" stroke="${accent}" stroke-width="6"/>
<circle cx="300" cy="290" r="5" fill="${accent}"/><circle cx="300" cy="360" r="5" fill="${accent}"/><circle cx="300" cy="430" r="5" fill="${accent}"/>`;
    default:
      return isBelt
        ? `<rect x="110" y="340" width="380" height="50" rx="8" fill="${fill}"/><rect x="270" y="326" width="70" height="78" rx="10" fill="none" stroke="${accent}" stroke-width="10"/>`
        : `<rect x="170" y="260" width="260" height="260" rx="28" fill="${fill}"/><path d="M230 260 C230 170 370 170 370 260" fill="none" stroke="${accent}" stroke-width="14"/>`;
  }
}

/** Inline SVG placeholder (no external or copyrighted images). */
export function productSvg(p: Product, n: number): string {
  const colours = Array.from(new Set(p.variants.map((v) => v.colour)));
  const colour = colours[(n - 1) % colours.length];
  const base = hexFor(colour);
  const bg = shade("#efe7dc", n === 2 ? -10 : n === 3 ? 6 : 0);
  const isBelt = /belt/i.test(p.name);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="600" height="750" viewBox="0 0 600 750" role="img" aria-label="${esc(p.name)}">
<rect width="600" height="750" fill="${bg}"/>
<circle cx="300" cy="360" r="250" fill="${shade(bg, 12)}"/>
${shape(p.category, base, shade(base, -45), isBelt)}
<text x="300" y="650" text-anchor="middle" font-family="Georgia,serif" font-size="26" fill="#3a3128">${esc(p.name)}</text>
<text x="300" y="690" text-anchor="middle" font-family="sans-serif" font-size="16" letter-spacing="4" fill="#8a7f72">DESI THREADS</text>
</svg>`;
}

/** Size chart as an image (the HTML table is withheld when F09 is on). */
export function sizeChartSvg(title: string, html: string): string {
  const rows = [...html.matchAll(/<tr>(.*?)<\/tr>/g)].map((m) =>
    [...m[1].matchAll(/<t[hd]>(.*?)<\/t[hd]>/g)].map((c) => c[1]),
  );
  const cols = rows[0]?.length ?? 1;
  const colW = 150;
  const width = 40 + cols * colW;
  const height = 110 + rows.length * 40;
  const cells = rows
    .map((r, ri) =>
      r
        .map((c, ci) => {
          const x = 20 + ci * colW + colW / 2;
          const y = 100 + ri * 40;
          const bold = ri === 0 ? ' font-weight="700"' : "";
          return `<text x="${x}" y="${y}" text-anchor="middle" font-family="sans-serif" font-size="16"${bold} fill="#333">${esc(c)}</text>`;
        })
        .join(""),
    )
    .join("");
  const lines = rows.map((_, ri) => `<line x1="20" y1="${112 + ri * 40}" x2="${width - 20}" y2="${112 + ri * 40}" stroke="#ddd"/>`).join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="Size chart">
<rect width="${width}" height="${height}" fill="#fff"/>
<text x="20" y="44" font-family="Georgia,serif" font-size="22" fill="#3a3128">${esc(title)}</text>
${lines}${cells}</svg>`;
}
