/** Generated placeholder "screenshots" of the demo store (not part of the dashboard theme, so fixed colours are fine). */
interface SceneInput {
  scene: string;
  caption: string;
  status: number;
  n: number;
}

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const FONT = "font-family=\"Inter, Segoe UI, Arial, sans-serif\"";

const rect = (x: number, y: number, w: number, h: number, fill: string, rx = 8, extra = "") => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${rx}" fill="${fill}" ${extra}/>`;
const text = (x: number, y: number, s: string, size = 18, fill = "#1f2937", weight = 400, anchor = "start") => `<text x="${x}" y="${y}" font-size="${size}" fill="${fill}" font-weight="${weight}" text-anchor="${anchor}" ${FONT}>${esc(s)}</text>`;

function product(price: boolean) {
  return [
    rect(80, 150, 480, 440, "#e5e7eb", 12),
    text(320, 380, "[ product photo ]", 20, "#9ca3af", 400, "middle"),
    text(620, 200, "White Court Sneaker", 34, "#111827", 700),
    price ? text(620, 250, "₹2,499", 30, "#111827", 600) : rect(620, 225, 220, 34, "#f3f4f6", 6) + text(630, 249, "price loads with JavaScript…", 15, "#9ca3af"),
    text(620, 300, "Size", 16, "#6b7280"),
    ...[7, 8, 9, 10].map((s, i) => rect(620 + i * 64, 315, 54, 44, i === 2 ? "#111827" : "#ffffff", 8, 'stroke="#d1d5db"') + text(647 + i * 64, 344, String(s), 17, i === 2 ? "#ffffff" : "#111827", 500, "middle")),
    rect(620, 400, 300, 52, "#111827", 10),
    text(770, 433, "Add to cart", 19, "#ffffff", 600, "middle"),
  ].join("");
}

const modal = (title: string, body: string, cta: string) =>
  rect(0, 70, 1280, 730, "#000000", 0, 'opacity="0.55"') +
  rect(400, 250, 480, 300, "#ffffff", 16) +
  text(640, 310, title, 26, "#111827", 700, "middle") +
  text(640, 350, body, 16, "#6b7280", 400, "middle") +
  rect(440, 385, 400, 48, "#ffffff", 8, 'stroke="#9ca3af"') +
  text(460, 416, "6 digit pincode", 16, "#9ca3af") +
  rect(440, 460, 400, 52, "#111827", 10) +
  text(640, 493, cta, 18, "#ffffff", 600, "middle");

function body(scene: string): string {
  switch (scene) {
    case "landing":
      return rect(0, 70, 1280, 420, "#e0e7ff", 0) + text(640, 250, "Run into a new season", 56, "#1e1b4b", 700, "middle") + text(640, 310, "Free shipping over ₹999", 22, "#4338ca", 400, "middle") + rect(540, 350, 200, 54, "#1e1b4b", 10) + text(640, 385, "Shop now", 19, "#ffffff", 600, "middle");
    case "pdp":
    case "variant":
    case "delivery":
      return product(true) + (scene === "delivery" ? rect(620, 475, 300, 40, "#ffffff", 8, 'stroke="#d1d5db"') + text(634, 501, "Delivery to pincode: not set", 15, "#b45309") : "");
    case "pdp_no_price":
      return product(false);
    case "pincode_modal":
      return product(true) + modal("Enter your pincode", "We need it to check delivery before adding to cart.", "Continue");
    case "login_otp":
      return rect(430, 170, 420, 440, "#ffffff", 16, 'stroke="#e5e7eb"') + text(640, 240, "Log in to continue", 28, "#111827", 700, "middle") + rect(470, 290, 340, 48, "#ffffff", 8, 'stroke="#9ca3af"') + text(490, 321, "Mobile number", 16, "#9ca3af") + rect(470, 360, 340, 52, "#111827", 10) + text(640, 393, "Send OTP", 18, "#ffffff", 600, "middle") + text(640, 450, "We will text you a 6 digit code", 14, "#6b7280", 400, "middle");
    case "app_overlay":
      return product(true) + rect(0, 70, 1280, 730, "#111827", 0, 'opacity="0.92"') + text(640, 340, "Get the app for a better experience", 38, "#ffffff", 700, "middle") + rect(500, 390, 280, 56, "#ffffff", 10) + text(640, 426, "Download the app", 19, "#111827", 600, "middle") + text(640, 490, "Continue in browser is not available", 14, "#9ca3af", 400, "middle");
    case "size_guide_image":
      return rect(300, 130, 680, 560, "#f3f4f6", 12) + text(640, 400, "[ size chart as an image: no alt text, no table ]", 20, "#9ca3af", 400, "middle") + text(640, 170, "Size guide", 26, "#111827", 700, "middle");
    case "checkout_error":
      return rect(380, 130, 520, 560, "#ffffff", 16, 'stroke="#e5e7eb"') + text(420, 190, "Checkout", 28, "#111827", 700) + rect(420, 220, 440, 48, "#ffffff", 8, 'stroke="#9ca3af"') + text(436, 250, "Name: Test Agent", 16, "#111827") + rect(420, 300, 440, 48, "#ffffff", 8, 'stroke="#dc2626" stroke-width="2"') + text(436, 330, "+91 98765 43210", 16, "#111827") + text(420, 372, "Enter a valid 10 digit phone number", 14, "#dc2626") + rect(420, 420, 440, 52, "#9ca3af", 10) + text(640, 453, "Place order", 18, "#ffffff", 600, "middle");
    case "out_of_stock":
      return product(true) + rect(620, 400, 300, 52, "#9ca3af", 10) + text(770, 433, "Out of stock", 19, "#ffffff", 600, "middle");
    default:
      return "";
  }
}

export function renderScene(s: SceneInput): string {
  const bad = s.status >= 400;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 800" width="1280" height="800" role="img" aria-label="${esc(s.caption)}">
${rect(0, 0, 1280, 800, "#fafafa", 0)}
${rect(0, 0, 1280, 70, "#ffffff", 0, 'stroke="#e5e7eb"')}
${rect(20, 22, 12, 12, "#f87171", 6)}${rect(40, 22, 12, 12, "#fbbf24", 6)}${rect(60, 22, 12, 12, "#34d399", 6)}
${rect(110, 16, 760, 36, "#f3f4f6", 18)}${text(134, 40, "demo-store.example", 15, "#6b7280")}
${text(1050, 40, "Step " + s.n, 15, "#6b7280")}
${body(s.scene)}
${rect(0, 740, 1280, 60, bad ? "#fef2f2" : "#f0fdf4", 0)}
${text(30, 777, `${bad ? "✕" : "✓"} ${s.caption}${bad ? ` · HTTP ${s.status}` : ""}`, 17, bad ? "#b91c1c" : "#15803d", 600)}
</svg>
`;
}
