import fs from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { hashIp, hashSid, ipPrefix, sha256 } from "../../lib/client";
import { LOG_FIELDS, buildRecord, isAssetPath, refererDomainPath, toNginxLine, writeRecord, type RequestInfo } from "../../lib/logger";
import { scrubQuery } from "../../lib/scrub";

const SALT = "unit-salt";
const SCRATCH = path.join(__dirname, "..", "..", ".e2e-tmp");

function req(over: Partial<RequestInfo> = {}): RequestInfo {
  return {
    requestId: "11111111-2222-4333-8444-555555555555",
    startMs: Date.UTC(2026, 10, 18, 8, 30, 15, 123),
    method: "GET",
    url: "/p/navy-court-sneaker?utm=a",
    headers: {
      host: "localhost:3100",
      "user-agent": "Mozilla/5.0 Test",
      referer: "https://www.google.com/search?q=secret&x=1",
      accept: "text/html",
      cookie: "dt_sid=abc; other=secret-cookie",
    },
    ip: "203.0.113.77",
    sid: "abc",
    ...over,
  };
}

describe("buildRecord", () => {
  const rec = buildRecord(req(), { status: 200, bytesOut: 1234, durationMs: 12.4 }, { salt: SALT });

  it("has exactly the PRD 9.2 fields", () => {
    expect(Object.keys(rec).sort()).toEqual([...LOG_FIELDS].sort());
  });
  it("formats ts as ISO-8601 UTC with milliseconds", () => {
    expect(rec.ts).toBe("2026-11-18T08:30:15.123Z");
  });
  it("hashes the ip with the salt and keeps only the /24", () => {
    expect(rec.ip_hash).toBe(sha256(`${SALT}203.0.113.77`));
    expect(rec.ip_hash).toBe(hashIp("203.0.113.77", SALT));
    expect(rec.ip_prefix).toBe("203.0.113.0/24");
    expect(JSON.stringify(rec)).not.toContain("203.0.113.77");
  });
  it("logs only the dt_sid hash and never other cookies", () => {
    expect(rec.cookie_sid_hash).toBe(hashSid("abc", SALT));
    expect(JSON.stringify(rec)).not.toContain("secret-cookie");
  });
  it("reduces the referer to domain and path", () => {
    expect(rec.referer).toBe("www.google.com/search");
    expect(refererDomainPath("not a url")).toBeNull();
  });
  it("records status, bytes and duration as integers", () => {
    expect(rec).toMatchObject({ status: 200, bytes_out: 1234, duration_ms: 12, event_type: "request", is_asset: false, meta: {} });
  });
  it("includes synth_session_id only in synth mode", () => {
    const r = req({ headers: { ...req().headers, "x-synth-session": "sess-9" } });
    const res = { status: 200, bytesOut: 1, durationMs: 1 };
    expect(buildRecord(r, res, { salt: SALT }).meta).toEqual({});
    expect(buildRecord(r, res, { salt: SALT, synthMode: true }).meta).toEqual({ synth_session_id: "sess-9" });
  });
  it("carries signature headers through", () => {
    const r = req({ headers: { ...req().headers, signature: "sig1=:abc:", "signature-input": "sig1=(...)", "signature-agent": '"https://x.test"' } });
    const out = buildRecord(r, { status: 200, bytesOut: 1, durationMs: 1 }, { salt: SALT });
    expect(out).toMatchObject({ signature: "sig1=:abc:", signature_input: "sig1=(...)", signature_agent: '"https://x.test"' });
  });
  it("classifies assets", () => {
    expect(isAssetPath("/_next/static/chunks/a.js")).toBe(true);
    expect(isAssetPath("/img/p/x-1.svg")).toBe(true);
    expect(isAssetPath("/p/x")).toBe(false);
  });
});

describe("ipPrefix", () => {
  it("uses /24 for v4, /48 for v6 and unwraps v4-mapped addresses", () => {
    expect(ipPrefix("10.20.30.40")).toBe("10.20.30.0/24");
    expect(ipPrefix("2001:db8:abcd:12:1:2:3:4")).toBe("2001:db8:abcd::/48");
    expect(ipPrefix("2001:db8::1")).toBe("2001:db8:0::/48");
    expect(ipPrefix("::ffff:192.168.1.9")).toBe("192.168.1.0/24");
    expect(ipPrefix("garbage")).toBeNull();
  });
});

describe("scrubQuery", () => {
  it("redacts phone, email and otp-like values but keeps harmless params", () => {
    expect(scrubQuery("q=kurta&phone=9876543210")).toBe("q=kurta&phone=REDACTED");
    expect(scrubQuery("q=a%40b.com")).toBe("q=REDACTED");
    expect(scrubQuery("otp=123456&pincode=560001")).toBe("otp=REDACTED&pincode=560001");
    expect(scrubQuery("x=98765%2043210")).toBe("x=REDACTED");
    expect(scrubQuery("EMAIL=foo")).toBe("EMAIL=REDACTED");
  });
  it("handles empty and bare values", () => {
    expect(scrubQuery("")).toBe("");
    expect(scrubQuery(undefined)).toBe("");
    expect(scrubQuery("?q=shirt")).toBe("q=shirt");
    expect(scrubQuery("someone@example.com")).toBe("REDACTED");
  });
});

describe("toNginxLine", () => {
  it("emits combined format plus signature fields without the raw ip", () => {
    const rec = buildRecord(
      req({ headers: { ...req().headers, signature: "sig1=:abc:" } }),
      { status: 404, bytesOut: 77, durationMs: 1 },
      { salt: SALT },
    );
    const line = toNginxLine(rec);
    expect(line).toMatch(/^203\.0\.113\.0 - - \[18\/Nov\/2026:08:30:15 \+0000\] "GET \/p\/navy-court-sneaker\?utm=a HTTP\/1\.1" 404 77 /);
    expect(line).toContain('"www.google.com/search" "Mozilla/5.0 Test" "sig1=:abc:" "-" "-"');
    expect(line).not.toContain("203.0.113.77");
  });
});

describe("writeRecord", () => {
  const dirs: string[] = [];
  afterEach(() => {
    delete process.env.AGENTLENS_DATA_DIR;
    delete process.env.AGENTLENS_NGINX_LOG;
    for (const d of dirs.splice(0)) fs.rmSync(d, { recursive: true, force: true });
  });

  it("appends one JSON line per record to logs/access-YYYY-MM-DD.jsonl under AGENTLENS_DATA_DIR", () => {
    fs.mkdirSync(SCRATCH, { recursive: true });
    const dir = fs.mkdtempSync(path.join(SCRATCH, "log-"));
    dirs.push(dir);
    process.env.AGENTLENS_DATA_DIR = dir;
    process.env.AGENTLENS_NGINX_LOG = "1";
    const rec = buildRecord(req(), { status: 200, bytesOut: 5, durationMs: 1 }, { salt: SALT });
    writeRecord(rec);
    writeRecord(rec);
    const lines = fs.readFileSync(path.join(dir, "logs", "access-2026-11-18.jsonl"), "utf8").trim().split("\n");
    expect(lines).toHaveLength(2);
    expect(JSON.parse(lines[0]).request_id).toBe(rec.request_id);
    expect(fs.readFileSync(path.join(dir, "logs", "access.nginx.log"), "utf8").trim().split("\n")).toHaveLength(2);
  });
});
