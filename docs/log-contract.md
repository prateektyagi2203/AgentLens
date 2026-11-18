# Log and behaviour contract (shared by store, synth, pipeline)

Source of truth for the record schema is PRD section 9.2 (`docs/PRD.md`). This file pins the open details so the store (writer), synthetic generator (writer) and pipeline (reader) agree. The store must NOT log friction labels (PRD 9.2, D10); only generic API-level signals below.

## Files
- Logs: `<data>/logs/access-YYYY-MM-DD.jsonl`, one JSON object per line. `<data>` = `AGENTLENS_DATA_DIR` (default `<repo>/data`).
- Orders: `<data>/orders.jsonl` -> `{order_id, session_cookie_id (dt_sid hash), cart_value, ts, payment_method}`.
- Ground truth (synth only): `<data>/ground_truth/gt-<run_id>.jsonl`.
- Friction state: `apps/store/config/friction.json` -> `{ "toggles": {"F01": false, ... "F16": false}, "updated_at": "..." }`.
- Catalog: `apps/store/data/catalog.json` (the pipeline reads it as a read-only "catalog snapshot" for price checks).

## `meta` conventions (generic signals only)
| Situation | status | meta |
|---|---|---|
| Any API error | 4xx/5xx | `{"error_code": "<CODE>"}` |
| Pincode not yet validated, `POST /api/cart` | 409 | `PINCODE_REQUIRED` |
| Cart needs OTP login, `POST /api/cart` | 401 | `AUTH_REQUIRED` |
| `POST /api/otp/send` / `verify` | 200 / 200 or 400 | `{"error_code":"OTP_INVALID"}` on bad code |
| Out-of-stock variant, `GET /api/products/{id}/variants` | 409 | `OUT_OF_STOCK` |
| Bad phone, `POST /api/checkout` | 422 | `PHONE_FORMAT` |
| Captcha unsolved, `POST /api/checkout` | 403 | `CAPTCHA_REQUIRED` (and `GET /api/captcha` is requested by the checkout page when captcha is on) |
| COD needs OTP confirm, `POST /api/checkout` | 409 | `COD_OTP_REQUIRED` |
| Bot wall (any path) | 403 | `BOT_CHALLENGE` |
| Rate limit | 429 | `RATE_LIMITED` (+ `Retry-After` header) |
| `GET /api/serviceability` | 200 or 422 | `{"serviceable": true}` or `{"error_code":"PINCODE_UNSERVICEABLE"}` |
| Add to cart success | 201 | `{"product_id","unit_price","qty","cart_value"}` |
| Checkout success | 201 | `{"order_id","cart_value","payment_method"}` |
| PDP view | 200 | `{"product_id"}` |
| Beacon | 204 | `event_type="beacon"` |
| Order | -- | extra line `event_type="order"`, `meta={"order_id","cart_value","payment_method"}` |
| Config change | -- | `event_type="config_change"`, `meta={"toggles":{...},"changed":["F05"]}` |
| Synth only (`AGENTLENS_SYNTH_MODE=1`) | -- | `meta.synth_session_id` from header `X-Synth-Session` |

UI-only friction (F07 app interstitial, F08 spin-wheel, F09 image-only size guide, F03 JS-only price, F04 missing JSON-LD) leaves NO label in logs. F13 shows as large `duration_ms`. F14 only changes `robots.txt` content. F11 shows as cart `unit_price`/`cart_value` differing from the PDP/catalog price.

## Ports
Store 3100, Dashboard 3101, API 8100 (ADR-004). Ports 3000 and 8000 are used by unrelated projects on this machine: never touch processes listening there.
