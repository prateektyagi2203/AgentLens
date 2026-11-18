# Agent Readiness Report

Window: 2026-11-05 to 2026-11-11 (7 days) - synthetic demo data

## Headline

- AI-agent sessions: 4,145 (14.7% of all sessions)
- Agent conversion: 3.5% vs human conversion 4.2%
- Estimated monthly revenue at risk from agent blockers: ₹27.2 L (range ₹14.5 L - ₹43.6 L)

## Top fixes

1. **Make the pincode optional before cart** (B05, effort S) - about ₹12.6 L per month at risk
2. **Normalise phone numbers and relax validation** (B10, effort S) - about ₹4.5 L per month at risk
3. **Allow guest cart, defer login to checkout** (B06, effort M) - about ₹4.9 L per month at risk

## Ranked blockers

| ID | Blocker | Stage | Sessions | Share of failed | Monthly risk |
|---|---|---|---|---|---|
| B05 | Pincode wall | S5 | 1240 | 31.0% | ₹6.7 L - ₹20.2 L (base ₹12.6 L) |
| B06 | Login / OTP wall before cart | S5 | 480 | 12.0% | ₹2.6 L - ₹7.8 L (base ₹4.9 L) |
| B10 | Checkout validation failure | S7 | 200 | 5.0% | ₹2.4 L - ₹7.2 L (base ₹4.5 L) |
| B03 | JS-only price and stock | S2 | 600 | 15.0% | ₹72,411 - ₹2.2 L (base ₹1.4 L) |
| B09 | Size guide image-only | S3 | 260 | 6.5% | ₹54,912 - ₹1.6 L (base ₹1 L) |
| B11 | Unsupported payment step | S7 | 40 | 1.0% | ₹48,274 - ₹1.4 L (base ₹90,514) |
| B07 | App-download interstitial | S2 | 320 | 8.0% | ₹38,619 - ₹1.2 L (base ₹72,411) |
| B08 | Out-of-stock dead end | S3 | 120 | 3.0% | ₹25,344 - ₹76,032 (base ₹47,520) |

## Honest limitations

- Identity coverage: only Verified (cryptographically signed) and Declared (self-identifying user agent) agents are counted with confidence. Suspected agents are inferred from behaviour and can be wrong.
- Agents that disguise themselves as ordinary browsers are only partly visible.
- Revenue at risk is an estimate: sessions blocked x recoverable rate x stage probability x average order value. It is not lost revenue measured from payments.
