# Agent Readiness Report

*Data window 2026-11-01 to 2026-11-07 (7 days). Filters: segment: all agents. Generated 2026-11-18 11:56 UTC. All money in INR; figures are estimates per 30 days.*

## Executive summary

Between 2026-11-01 and 2026-11-07 (7 days), all agents generated 1,489 of 5,823 sessions (25.6%). Agents converted at 0.0% against 2.5% for human visitors. The biggest blocker is Login / OTP wall before cart (B06): it ended 417 agent sessions (28% of failed ones). Across all blockers AgentLens estimates ₹19.3 L of agent revenue at risk per month (range ₹10.3 L to ₹30.8 L). After the change "F03 off; F05 off; F06 off", agent conversion moved from 0.0% to 5.1% and estimated risk fell from ₹19.3 L to ₹4.1 L per month.

## Headline numbers

| Metric | Value |
|---|---|
| Agent sessions | 1,489 (25.6% of 5,823 sessions) |
| Agent conversion | 0.0% (0 orders) |
| Human conversion | 2.5% |
| Agent revenue in window | ₹0 (₹0) |
| Revenue at risk per month | **₹19.3 L** (range ₹10.3 L to ₹30.8 L) |
| Identity coverage | 77.8% (Verified 354, Declared 805, Suspected 330) |
| Failed agent sessions diagnosed | 88% (unknown cause: 0%) |

## Agent vs human funnel

| Stage | Agents reaching | Agents % of S1 | Humans reaching | Humans % of S1 |
|---|---:|---:|---:|---:|
| S1 Landing / Search | 1,489 | 100.0% | 4,334 | 100.0% |
| S2 Product page | 1,209 | 81.2% | 3,502 | 80.8% |
| S3 Variant selected | 551 | 37.0% | 417 | 9.6% |
| S4 Delivery check | 447 | 30.0% | 347 | 8.0% |
| S5 Added to cart | 0 | 0.0% | 211 | 4.9% |
| S6 Checkout started | 0 | 0.0% | 209 | 4.8% |
| S7 Checkout submitted | 0 | 0.0% | 109 | 2.5% |
| S8 Order placed | 0 | 0.0% | 109 | 2.5% |

## Top blockers

| # | Blocker | Stage | Agent sessions | Revenue at risk / month (base, range) | Effort | Replay |
|---:|---|---|---:|---|---|---|
| 1 | B06 Login / OTP wall before cart | S5 Added to cart | 417 | **₹12.2 L** (₹6.5 L to ₹19.5 L) | M | Confirmed |
| 2 | B09 Size guide is image-only | S3 Variant selected | 221 | **₹3.3 L** (₹1.7 L to ₹5.2 L) | S | Confirmed |
| 3 | B05 Pincode / serviceability wall | S5 Added to cart | 89 | **₹2.6 L** (₹1.4 L to ₹4.2 L) | S | Confirmed |
| 4 | B03 JS-only product content | S2 Product page | 498 | **₹87,687** (₹46,767 to ₹1.4 L) | M | Confirmed |
| 5 | B08 Out-of-stock dead end (low sample) | S3 Variant selected | 15 | **₹22,181** (₹11,830 to ₹35,489) | S | Not run |

## Recommendations

1. **Login / OTP wall before cart** (B06, effort M, owner Product): Allow guest cart and defer login to checkout, or offer guest checkout.
   - Worth about ₹12.2 L per month.
   - How to verify: Add-to-cart 401 count falls; PDP to cart step conversion for agents rises.
   - Why: 22% of failed agent sessions (417) ended on login / otp wall before cart. Typical failing call: POST /api/cart -> 401 AUTH_REQUIRED. Fixing it could recover about ₹170,734 a month.
2. **Size guide is image-only** (B09, effort S, owner Content): Provide an HTML table size guide.
   - Worth about ₹3.3 L per month.
   - How to verify: Site check "size guide has HTML table" passes; size-guide sessions continue to cart.
   - Why: 22% of failed agent sessions (419) ended on size guide is image-only. Typical failing call: GET /size-guide/mens-sneakers -> 200. Fixing it could recover about ₹73,606 a month.
3. **Pincode / serviceability wall** (B05, effort S, owner Product): Make pincode optional before cart, accept it by URL or API, and show the delivery promise without a modal.
   - Worth about ₹2.6 L per month.
   - How to verify: Add-to-cart 409 PINCODE_REQUIRED count falls to near zero; PDP to cart step conversion for agents rises.
   - Why: 5% of failed agent sessions (89) ended on pincode / serviceability wall. Typical failing call: POST /api/cart -> 409 PINCODE_REQUIRED. Fixing it could recover about ₹36,440 a month.

## Replay evidence

A replay agent re-ran the shopping task against the test store to check each hypothesis (identified as AgentLens-Replay, test data only).

| Blocker | Verdict | Mode | Steps | When | What happened |
|---|---|---|---:|---|---|
| B03 | Confirmed | fetch | 4 | 2026-11-18 11:52 UTC | Reproduced B03 (Price/stock exist only after client-side JS): no price in server-rendered HTML or JSON-LD (client-side only) (step 4). |
| B05 | Confirmed | fetch | 4 | 2026-11-18 11:52 UTC | Reproduced B05 (Add to cart is gated by a pincode check): a pincode modal is server-rendered on the product page and blocks interaction (step 4). |
| B06 | Confirmed | fetch | 10 | 2026-11-18 11:51 UTC | Reproduced B06 (Add to cart requires an OTP login): add to cart rejected with 401 AUTH_REQUIRED (OTP login before cart) (step 10). |
| B07 | Confirmed | browser | 5 | 2026-11-18 11:52 UTC | Reproduced B07 (A full-screen overlay covers the page): a full-screen app-download interstitial covers the product page (close button appeared after 3061 ms) (step 5). |
| B09 | Confirmed | fetch | 6 | 2026-11-18 11:52 UTC | Reproduced B09 (The size guide is an image with no HTML table): size guide is an image only; no HTML table to read (step 6). |
| B10 | Confirmed | fetch | 16 | 2026-11-18 11:52 UTC | Reproduced B10 (Checkout rejects a plain 10-digit phone number): checkout rejected a plain 10-digit phone (422 PHONE_FORMAT); only '+91 XXXXX XXXXX' passes (step 16). |

## Before and after

Comparison: Around "F03 off; F05 off; F06 off" (2026-11-01 to 2026-11-07 vs 2026-11-08 to 2026-11-14).

| Metric | Before | After |
|---|---:|---:|
| Agent sessions | 1,489 | 1,420 |
| Agent conversion | 0.0% | 5.1% |
| Agent revenue | ₹0 | ₹1.6 L |
| Revenue at risk / month | ₹19.3 L | ₹4.1 L |

The change in conversion is statistically significant (two-proportion z-test, p < 0.001).

Biggest changes by blocker: B06 ₹12.2 L to ₹0; B05 ₹2.6 L to ₹0; B09 ₹3.3 L to ₹1.3 L; B03 ₹87,687 to ₹0.

## Methodology and assumptions

- Agents are identified from access logs: Verified (Web Bot Auth signature), Declared (known user-agent), Suspected (behavioural score). Humans are everything else.
- Each failed agent session is assigned one terminal blocker by deterministic rules over its requests; sessions with no matching rule are reported as Unknown and never priced.
- Revenue at risk = blocked sessions x recoverable rate (low 0.4, base 0.6, high 0.8) x probability the session would have bought x average order value (₹2,200) x 4.29 (scales 7 days to 30).
- The probability uses agent conversion past the blocking stage, falling back to human conversion where agent samples are thin (fewer than 30 sessions are flagged low sample). The band on it is +/-20%.
- Replays confirm a hypothesis on a test store; they do not prove the same blocker affected a specific real session.

## Honest limitations

Agents that run inside the shopper's own browser (for example, browser extensions) look like humans at the server. AgentLens can only flag them as Suspected through behaviour, if at all. The identity coverage metric shows how much traffic is confidently identified.
