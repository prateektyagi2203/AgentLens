# Security policy

AgentLens is a demo and portfolio project that runs on synthetic data. There is no production deployment and no real
customer data. Reports are still welcome.

## Reporting a vulnerability

Please do **not** open a public issue. Use GitHub's private vulnerability reporting on the repository
(Security tab, "Report a vulnerability") at <https://github.com/prateektyagi2203/AgentLens>. Include the affected
component (store, API, dashboard, replay agent), reproduction steps and the commit you tested. Expect an acknowledgement
within a week. This is a spare-time project, so there is no SLA.

## Secrets

- Nothing secret is committed. `.env` is gitignored; `.env.example` contains placeholders only (`change-me`, an empty
  `OPENAI_API_KEY`). CI fails the build when it finds something that looks like an OpenAI or Google API key.
- The one private key in the repo, `apps/store/config/test-operator.private.pem`, is a **deliberately public test key**
  for the fictional operator `agents.desithreads.test` (see `apps/store/config/README.md`). It protects nothing.
- If you run AgentLens beyond a local demo, set `AGENTLENS_IP_SALT` and `AGENTLENS_ADMIN_PASSWORD` to your own values.
  Rotating the salt breaks session linkage for existing data.

## Data handling

- Logs and the database never hold raw IPs, phone numbers, emails, addresses, OTPs or request bodies. IPs are salted
  hashes plus a coarse prefix; the OTP flow logs nothing about the code or the number.
- The public demo snapshot is generated from synthetic data only. `agentlens export-snapshot` refuses to write a
  snapshot that contains ground-truth fields, raw IPv4 addresses or e-mail addresses.
- `DEMO_MODE=1` disables the store `/admin` page and `/api/admin/*`.

## Safe use

- The replay agent only contacts hosts on its allow-list (`config/replay.yaml` plus `PUBLIC_STORE_HOST`). See the
  safety section of [docs/replay-agent.md](docs/replay-agent.md).
- Point real agents only at your own demo store (docs/real-agent-runs.md). Never test third-party sites without permission,
  and never use real payment details.
- Dependencies are locked (`uv.lock`, `pnpm-lock.yaml`); CI runs `pip-audit` and `pnpm audit` (advisory only).
