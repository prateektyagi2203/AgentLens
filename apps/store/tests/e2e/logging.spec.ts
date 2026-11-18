import fs from "node:fs";
import path from "node:path";
import { LOG_FIELDS } from "../../lib/logger";
import { addToCart, dataDir, inStockProduct, logsDir, test, expect, waitForLog } from "./helpers";

function allDataText(): string {
  const files: string[] = [];
  const walk = (dir: string) => {
    if (!fs.existsSync(dir)) return;
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else files.push(p);
    }
  };
  walk(dataDir());
  return files.map((f) => fs.readFileSync(f, "utf8")).join("\n");
}

test.describe("capture layer", () => {
  test("PII never reaches the logs or the orders file", async ({ client, setToggles }) => {
    await setToggles();
    const marker = `pii${Date.now()}`;
    const secrets = {
      phone: "+91 98765 43210",
      email: `${marker}@example.com`,
      address: `221B Baker Street ${marker}`,
      name: `Buyer ${marker}`,
      otp: "654321",
    };
    await addToCart(client);
    await client.get(
      `/search?q=kurta&phone=9876543210&email=${encodeURIComponent(secrets.email)}&otp=${secrets.otp}&address=${encodeURIComponent(secrets.address)}`,
    );
    await client.post("/api/otp/send", { data: { phone: secrets.phone, email: secrets.email } });
    const res = await client.post("/api/checkout", {
      data: {
        name: secrets.name,
        phone: secrets.phone,
        email: secrets.email,
        address: secrets.address,
        payment_method: "COD",
        cod_otp: secrets.otp,
      },
    });
    expect(res.status()).toBe(201);
    await waitForLog((r) => r.event_type === "order");
    await waitForLog((r) => r.path === "/api/checkout");

    const text = allDataText();
    expect(text).toContain("/api/checkout");
    for (const needle of [marker, "98765 43210", "9876543210", "9876543210".replace(/(\d{5})(\d{5})/, "$1 $2"), "Baker Street", secrets.otp]) {
      expect(text, `"${needle}" leaked into logs/orders`).not.toContain(needle);
    }
  });

  test("every log line matches the PRD 9.2 schema", async ({ client, setToggles, newPage }) => {
    await setToggles("F01");
    await client.get("/api/products/does-not-exist/variants");
    await client.get("/", { headers: { "user-agent": "python-httpx/0.27", "x-synth-session": "must-not-appear" } });
    await client.post("/api/beacon", { data: { e: "view" } });
    await setToggles();
    await addToCart(client);
    await client.post("/api/checkout", {
      data: { name: "E2E", phone: "+91 98765 43210", address: "x 560001", payment_method: "UPI" },
    });
    const { page } = await newPage();
    await page.goto(`/p/${inStockProduct().slug}`, { waitUntil: "networkidle" });
    await setToggles("F03", "F05", "F06", "F07", "F09", "F10");
    await waitForLog((r) => r.event_type === "beacon");
    await waitForLog((r) => r.event_type === "config_change");

    const lines = fs
      .readdirSync(logsDir())
      .filter((f) => /^access-\d{4}-\d{2}-\d{2}\.jsonl$/.test(f))
      .flatMap((f) => fs.readFileSync(path.join(logsDir(), f), "utf8").split("\n").filter(Boolean));
    expect(lines.length).toBeGreaterThan(10);

    const nullableStrings = [
      "ip_prefix", "user_agent", "referer", "accept", "accept_language", "sec_ch_ua", "sec_fetch_site",
      "sec_fetch_mode", "sec_fetch_dest", "signature", "signature_input", "signature_agent", "cookie_sid_hash", "host",
    ];
    const events = new Set(["request", "beacon", "config_change", "order"]);
    const recs = lines.map((l) => JSON.parse(l) as Record<string, unknown>);
    for (const r of recs) {
      expect(Object.keys(r).sort()).toEqual([...LOG_FIELDS].sort());
      expect(r.ts).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
      expect(r.request_id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
      expect(typeof r.method).toBe("string");
      expect(String(r.path).startsWith("/")).toBe(true);
      expect(typeof r.query).toBe("string");
      expect(Number.isInteger(r.status)).toBe(true);
      expect(Number.isInteger(r.bytes_out) && (r.bytes_out as number) >= 0).toBe(true);
      expect(Number.isInteger(r.duration_ms) && (r.duration_ms as number) >= 0).toBe(true);
      expect(r.ip_hash).toMatch(/^[0-9a-f]{64}$/);
      expect(typeof r.is_asset).toBe("boolean");
      expect(events.has(r.event_type as string)).toBe(true);
      expect(r.meta && typeof r.meta === "object" && !Array.isArray(r.meta)).toBe(true);
      for (const k of nullableStrings) expect(r[k] === null || typeof r[k] === "string", k).toBe(true);
      if (r.cookie_sid_hash !== null) expect(r.cookie_sid_hash).toMatch(/^[0-9a-f]{64}$/);
      if (r.ip_prefix !== null) expect(r.ip_prefix).toMatch(/^(\d+\.\d+\.\d+\.0\/24|[0-9a-f:]+::\/48)$/);
      expect(JSON.stringify(r)).not.toContain("must-not-appear");
    }

    expect(recs.some((r) => r.is_asset === true && String(r.path).startsWith("/_next/"))).toBe(true);
    expect(recs.some((r) => r.is_asset === false && r.path === "/" && r.status === 403)).toBe(true);
    expect(recs.some((r) => r.event_type === "order" && r.status === 201)).toBe(true);
    expect(recs.some((r) => r.status === 404 && (r.meta as Record<string, unknown>).error_code === "PRODUCT_NOT_FOUND")).toBe(true);
    const pdp = recs.find((r) => String(r.path).startsWith("/p/") && r.status === 200);
    expect(pdp?.bytes_out).toBeGreaterThan(1000);
    expect(pdp?.user_agent).toContain("Mozilla");

    const nginx = fs.readFileSync(path.join(logsDir(), "access.nginx.log"), "utf8").trim().split("\n");
    expect(nginx.length).toBeGreaterThanOrEqual(recs.length);
    expect(nginx[0]).toMatch(/^\S+ - - \[\d{2}\/\w{3}\/\d{4}:\d{2}:\d{2}:\d{2} \+0000\] "[A-Z]+ \S+ HTTP\/1\.1" \d{3} \d+ "[^"]*" "[^"]*" "[^"]*" "[^"]*" "[^"]*"$/);
  });
});
