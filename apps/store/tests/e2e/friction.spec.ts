import { catalog, test, expect, addToCart, BROWSER_UA, DEV_OTP, inStockProduct, pickInStock, VALID_ORDER, waitForLog } from "./helpers";
import { formatINR } from "../../lib/format";

test.describe("friction toggles F01-F16: behaviour on vs off", () => {
  test("F01 bot wall: non-browser and agent UAs get a 403 challenge", async ({ client, setToggles }) => {
    await setToggles("F01");
    const blocked = await client.get("/", { headers: { "user-agent": "python-httpx/0.27.0" } });
    expect(blocked.status()).toBe(403);
    expect(await blocked.text()).toContain("Checking your browser");
    const agent = await client.get("/", { headers: { "user-agent": `${BROWSER_UA} ChatGPT-User/1.0` } });
    expect(agent.status()).toBe(403);
    expect((await client.get("/")).status()).toBe(200);
    const replay = await client.get("/", { headers: { "user-agent": "AgentLens-Replay/1.0 (+https://example.org)" } });
    expect(replay.status()).toBe(200);
    await waitForLog((r) => r.status === 403 && (r.meta as Record<string, unknown>).error_code === "BOT_CHALLENGE");

    await setToggles();
    expect((await client.get("/", { headers: { "user-agent": "python-httpx/0.27.0" } })).status()).toBe(200);
  });

  test("F02 captcha: checkout needs the solved captcha", async ({ client, setToggles }) => {
    await setToggles("F02");
    await addToCart(client);
    const denied = await client.post("/api/checkout", { data: VALID_ORDER });
    expect(denied.status()).toBe(403);
    expect((await denied.json()).error_code).toBe("CAPTCHA_REQUIRED");

    const svg = await (await client.get("/api/captcha")).text();
    const answer = [...svg.matchAll(/<text [^>]*>([A-Z0-9])<\/text>/g)].map((m) => m[1]).join("");
    expect(answer).toHaveLength(5);
    const ok = await client.post("/api/checkout", { data: { ...VALID_ORDER, captcha_answer: answer } });
    expect(ok.status()).toBe(201);

    await setToggles();
    await addToCart(client);
    expect((await client.post("/api/checkout", { data: VALID_ORDER })).status()).toBe(201);
    expect((await client.get("/api/captcha")).status()).toBe(404);
  });

  test("F03 JS-only price: price and stock are absent from server HTML and JSON-LD", async ({ client, setToggles, newPage }) => {
    const p = inStockProduct();
    const price = formatINR(p.price);
    await setToggles("F03");
    const html = await (await client.get(`/p/${p.slug}`)).text();
    expect(html).not.toContain(price);
    expect(html).not.toContain('"price"');
    expect(html).not.toContain("InStock");
    const { page } = await newPage();
    await page.goto(`/p/${p.slug}`);
    await expect(page.getByTestId("client-price")).toContainText(price);

    await setToggles();
    const full = await (await client.get(`/p/${p.slug}`)).text();
    expect(full).toContain(price);
    const ld = JSON.parse(/<script type="application\/ld\+json">(.*?)<\/script>/s.exec(full)![1]);
    expect(ld.offers).toMatchObject({ price: p.price, priceCurrency: "INR", availability: "https://schema.org/InStock" });
    expect(ld.hasVariant.length).toBe(p.variants.length);
  });

  test("F04 no structured data: JSON-LD is removed", async ({ client, setToggles }) => {
    const p = inStockProduct();
    await setToggles("F04");
    expect(await (await client.get(`/p/${p.slug}`)).text()).not.toContain("application/ld+json");
    await setToggles();
    const html = await (await client.get(`/p/${p.slug}`)).text();
    expect(html).toContain("application/ld+json");
    expect(html).toContain('"@type":"Product"');
  });

  test("F05 pincode wall: modal and 409 until a serviceable pincode is validated", async ({ client, setToggles, newPage }) => {
    await setToggles();
    expect((await addToCart(client)).status()).toBe(201);
    const { page: offPage } = await newPage();
    await offPage.goto(`/p/${inStockProduct().slug}`);
    await expect(offPage.getByTestId("add-to-cart")).toBeVisible();
    await expect(offPage.getByTestId("pincode-modal")).toHaveCount(0);

    await setToggles("F05");
    const denied = await addToCart(client);
    expect(denied.status()).toBe(409);
    expect((await denied.json()).error_code).toBe("PINCODE_REQUIRED");
    expect((await client.get("/api/serviceability?pincode=000000")).status()).toBe(422);
    expect((await client.get("/api/serviceability?pincode=560001")).status()).toBe(200);
    expect((await addToCart(client)).status()).toBe(201);

    const { page } = await newPage();
    await page.goto(`/p/${inStockProduct().slug}`);
    await expect(page.getByTestId("pincode-modal")).toBeVisible();
    await page.getByTestId("pincode-modal-input").fill("560001");
    await page.getByTestId("pincode-modal").getByRole("button", { name: "Check" }).click();
    await expect(page.getByTestId("pincode-modal")).toHaveCount(0);
  });

  test("F06 OTP before cart: 401 with redirect to /login until the OTP is verified", async ({ client, setToggles }) => {
    await setToggles();
    expect((await addToCart(client)).status()).toBe(201);

    await setToggles("F06");
    const denied = await addToCart(client);
    expect(denied.status()).toBe(401);
    expect(await denied.json()).toMatchObject({ error_code: "AUTH_REQUIRED", redirect: "/login" });
    expect((await client.post("/api/otp/send", { data: { phone: "9876543210" } })).status()).toBe(200);
    expect((await client.post("/api/otp/verify", { data: { otp: "000000" } })).status()).toBe(400);
    expect((await client.post("/api/otp/verify", { data: { otp: DEV_OTP } })).status()).toBe(200);
    expect((await addToCart(client)).status()).toBe(201);
  });


  test("F07 app interstitial: close button is hidden for 3 s", async ({ setToggles, newPage }) => {
    const slug = inStockProduct().slug;
    await setToggles("F07");
    const { page } = await newPage();
    await page.goto(`/p/${slug}`);
    await expect(page.getByTestId("app-interstitial")).toBeVisible();
    const close = page.getByTestId("app-interstitial-close");
    await expect(close).toHaveCount(0);
    await expect(close).toBeVisible({ timeout: 6000 });
    await close.click();
    await expect(page.getByTestId("app-interstitial")).toHaveCount(0);

    await setToggles();
    const { page: page2 } = await newPage();
    await page2.goto(`/p/${slug}`);
    await expect(page2.getByTestId("add-to-cart")).toBeVisible();
    await expect(page2.getByTestId("app-interstitial")).toHaveCount(0);
  });

  test("F08 spin-the-wheel popup covers the landing page", async ({ setToggles, newPage }) => {
    await setToggles("F08");
    const { page } = await newPage();
    await page.goto("/");
    await expect(page.getByTestId("spin-wheel")).toBeVisible();
    await page.getByText("No thanks").click();
    await expect(page.getByTestId("spin-wheel")).toHaveCount(0);

    await setToggles();
    const { page: page2 } = await newPage();
    await page2.goto("/");
    await expect(page2.getByRole("heading", { name: "Bestsellers" })).toBeVisible();
    await expect(page2.getByTestId("spin-wheel")).toHaveCount(0);
  });

  test("F09 size chart image-only: the HTML table disappears", async ({ client, setToggles }) => {
    await setToggles("F09");
    const only = await (await client.get("/size-guide/mens-shirts")).text();
    expect(only).not.toContain("<table");
    expect(only).toContain("/img/size/mens-shirts.svg");
    expect((await client.get("/img/size/mens-shirts.svg")).status()).toBe(200);

    await setToggles();
    const both = await (await client.get("/size-guide/mens-shirts")).text();
    expect(both).toContain("<table");
    expect(both).toContain("/img/size/mens-shirts.svg");
  });

  test("F10 strict phone: only +91 XXXXX XXXXX is accepted", async ({ client, setToggles }) => {
    await setToggles("F10");
    await addToCart(client);
    const bad = await client.post("/api/checkout", { data: { ...VALID_ORDER, phone: "9876543210" } });
    expect(bad.status()).toBe(422);
    expect((await bad.json()).error_code).toBe("PHONE_FORMAT");
    expect((await client.post("/api/checkout", { data: VALID_ORDER })).status()).toBe(201);

    await setToggles();
    await addToCart(client);
    expect((await client.post("/api/checkout", { data: { ...VALID_ORDER, phone: "9876543210" } })).status()).toBe(201);
  });

  test("F11 price mismatch: cart price differs for the flagged products", async ({ client, setToggles }) => {
    const flagged = catalog().products.filter((p) => p.price_mismatch);
    expect(flagged).toHaveLength(2);
    const p = flagged[0];
    const v = pickInStock(p);
    const add = () => client.post("/api/cart", { data: { product_id: p.id, size: v.size, colour: v.colour } });

    await setToggles("F11");
    const mismatched = await (await add()).json();
    expect(mismatched.unit_price).toBe(p.cart_price);
    expect(mismatched.unit_price).not.toBe(p.price);

    await setToggles();
    const fresh = await (await add()).json();
    expect(fresh.unit_price).toBe(p.price);
  });

  test("F12 rate limit: the 21st request in a minute gets 429 with Retry-After", async ({ client, setToggles }) => {
    await setToggles("F12");
    const statuses: number[] = [];
    let retryAfter: string | undefined;
    for (let i = 0; i < 22; i++) {
      const res = await client.get("/policies/returns");
      statuses.push(res.status());
      if (res.status() === 429) retryAfter = res.headers()["retry-after"];
    }
    expect(statuses.slice(0, 20).every((s) => s === 200)).toBe(true);
    expect(statuses.slice(20)).toEqual([429, 429]);
    expect(Number(retryAfter)).toBeGreaterThan(0);
    await waitForLog((r) => r.status === 429 && (r.meta as Record<string, unknown>).error_code === "RATE_LIMITED");

    await setToggles();
    for (let i = 0; i < 25; i++) expect((await client.get("/policies/returns")).status()).toBe(200);
  });

  test("F13 slow pages: the PDP takes 6-9 s longer", async ({ client, setToggles }) => {
    const slug = inStockProduct().slug;
    await setToggles("F13");
    const t0 = Date.now();
    expect((await client.get(`/p/${slug}`)).status()).toBe(200);
    const slow = Date.now() - t0;
    expect(slow).toBeGreaterThanOrEqual(5900);
    expect(slow).toBeLessThan(15_000);

    await setToggles();
    const t1 = Date.now();
    await client.get(`/p/${slug}`);
    expect(Date.now() - t1).toBeLessThan(3000);
  });

  test("F14 robots.txt: listed agent tokens are disallowed from /p/ and /checkout", async ({ client, setToggles }) => {
    await setToggles("F14");
    const on = await (await client.get("/robots.txt")).text();
    expect(on).toMatch(/User-agent: GPTBot\s+Disallow: \/p\/\s+Disallow: \/checkout/);
    expect(on).toContain("User-agent: ChatGPT-User");

    await setToggles();
    const off = await (await client.get("/robots.txt")).text();
    expect(off).not.toContain("Disallow: /p/");
    expect(off).not.toContain("Disallow: /checkout");
  });

  test("F15 COD OTP confirm: COD orders need an OTP, other methods do not", async ({ client, setToggles }) => {
    await setToggles("F15");
    await addToCart(client);
    const denied = await client.post("/api/checkout", { data: { ...VALID_ORDER, payment_method: "COD" } });
    expect(denied.status()).toBe(409);
    expect((await denied.json()).error_code).toBe("COD_OTP_REQUIRED");
    const ok = await client.post("/api/checkout", { data: { ...VALID_ORDER, payment_method: "COD", cod_otp: DEV_OTP } });
    expect(ok.status()).toBe(201);
    await addToCart(client);
    expect((await client.post("/api/checkout", { data: { ...VALID_ORDER, payment_method: "UPI" } })).status()).toBe(201);

    await setToggles();
    await addToCart(client);
    expect((await client.post("/api/checkout", { data: { ...VALID_ORDER, payment_method: "COD" } })).status()).toBe(201);
  });

  test("F16 out-of-stock dead end: bare 409 when on, alternatives when off", async ({ client, setToggles }) => {
    const p = catalog().products.find((x) => x.variants.some((v) => v.stock === 0))!;
    const oos = p.variants.find((v) => v.stock === 0)!;
    const url = `/api/products/${p.id}/variants?size=${encodeURIComponent(oos.size)}&colour=${encodeURIComponent(oos.colour)}`;

    await setToggles("F16");
    const dead = await client.get(url);
    expect(dead.status()).toBe(409);
    const deadBody = await dead.json();
    expect(deadBody.error_code).toBe("OUT_OF_STOCK");
    expect(deadBody.alternatives).toBeUndefined();

    await setToggles();
    const alt = await client.get(url);
    expect(alt.status()).toBe(200);
    const altBody = await alt.json();
    expect(altBody.available).toBe(false);
    expect(altBody.alternatives.variants.length).toBeGreaterThan(0);
  });
});
