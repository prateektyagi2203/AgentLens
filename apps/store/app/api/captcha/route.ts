import { NextResponse } from "next/server";
import crypto from "node:crypto";
import { apiContext, apiError } from "../../../lib/api";
import { readToggles } from "../../../lib/friction";

const ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";

/** Distorted-text captcha rendered as SVG; each glyph is its own <text> element. */
export async function GET(req: Request) {
  if (!readToggles().F02) return apiError(req, 404, "CAPTCHA_DISABLED");
  const { state } = apiContext(req);
  const code = Array.from({ length: 5 }, () => ALPHABET[crypto.randomInt(ALPHABET.length)]).join("");
  state.captchaAnswer = code;

  const glyphs = [...code]
    .map((ch, i) => {
      const x = 22 + i * 30;
      const y = 38 + crypto.randomInt(-5, 6);
      const rot = crypto.randomInt(-25, 26);
      return `<text x="${x}" y="${y}" font-size="28" font-family="monospace" font-weight="700" fill="#374151" transform="rotate(${rot} ${x} ${y})">${ch}</text>`;
    })
    .join("");
  const noise = Array.from({ length: 5 }, () => {
    const [a, b, c, d] = [0, 1, 2, 3].map((k) => crypto.randomInt(k % 2 ? 50 : 180));
    return `<line x1="${a}" y1="${b}" x2="${c}" y2="${d}" stroke="#9ca3af" stroke-width="1.2"/>`;
  }).join("");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="180" height="56" viewBox="0 0 180 56"><rect width="180" height="56" fill="#f3f4f6"/>${noise}${glyphs}</svg>`;
  return new NextResponse(svg, {
    status: 200,
    headers: { "Content-Type": "image/svg+xml", "Cache-Control": "no-store" },
  });
}
