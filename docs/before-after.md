# Before / After

Shows what happened to agent conversion and revenue at risk after a fix. Computed from `sessions` and `blocker_hits` with the
same impact model as the funnel and blockers pages, so the numbers always agree. Code: `services/api/compare.py`
(`agentlens.compare`).

## Functions

```python
from agentlens.compare import before_after, compare_windows, suggested_windows, two_proportion_z

compare_windows(con, a_from, a_to, b_from, b_to, *, segment="all_agents", operator=None, agent_class=None) -> dict
```
The `Compare` shape of `docs/api-contract.md` 3.8 (`GET /compare`): `{segment, a, b, delta, significance, suggested_windows}`.
`a`/`b` are window summaries (`window, sessions, converted, conversion, agent_revenue_inr, risk_inr{low,base,high}, funnel,
blocker_shares`); `delta` holds `sessions, conversion_pp, conversion_relative, agent_revenue_inr, risk_base_inr`
(`conversion_relative` is `null` when the Before conversion is 0). Dates are `YYYY-MM-DD`, inclusive. `segment` is
`all_agents | verified | declared | suspected | humans`.

```python
suggested_windows(con) -> list[{label, annotation_id, a:{from,to}, b:{from,to}}]
```
Equal-length windows (up to 7 days each) either side of every `config_change` / `marked_fixed` annotation; `note`
annotations are ignored.

```python
before_after(con, *, segment="all_agents", operator=None, agent_class=None, annotation_id=None) -> dict | None
```
`compare_windows` around the first suggested window (or `annotation_id`), plus
`{annotation_id, label, headline, blocker_deltas, control}`. `headline` has `sessions_before/after, conversion_before/after,
conversion_pp, agent_revenue_before_inr/after_inr, risk_before_inr/after_inr`; `blocker_deltas` lists
`{blocker_id, name, sessions_before, sessions_after, risk_before_inr, risk_after_inr}`, largest improvement first; `control` is the human conversion in the same
windows, a sanity check that the lift is not just seasonality. Returns `None` when there is no annotation or no data on both sides.

```python
two_proportion_z(x1, n1, x2, n2, min_sessions, alpha=0.05) -> dict
```
Two-sided pooled z-test on conversion. Below `min_sessions` per window the answer is "not enough data" (`z: null`); a non-significant
result says it could be noise.

All functions accept a read-only connection. The API's `/compare` route and the report call them; the CLI prints the same numbers:
`agentlens before-after`.

## Reproducing the lift

```powershell
agentlens synth scenario before-after --sessions 8000 --force   # 7 days Before (F03/F05/F06 on), 7 days After, config_change at the switch
agentlens run-all
agentlens before-after
agentlens report --format all --out data\reports
```

Result on the shipped scenario (8000 sessions, seed 1; window "F03 off; F05 off; F06 off", 986 vs 997 agent sessions):

| Metric | Before | After |
|---|---:|---:|
| Agent conversion | 0.0% | 6.0% (+6.0 pp, z = 7.8, p < 0.001) |
| Agent revenue | ₹0 | ₹1.1 L (₹1,11,980) |
| Revenue at risk / month | ₹12 L | ₹1.2 L |
| B06 (login wall) at risk | ₹9.5 L | ₹0 |
| B05 (pincode wall) at risk | ₹2.3 L | ₹0 |
| Humans (control) | 2.6% | 4.7% |

Caveats: the PRD expects roughly 3.5% to 7.5%. The Before state in `config/synth.yaml` has F06 on, which stops every agent before add to
cart, so the Before conversion is exactly 0% and a relative lift is undefined. The direction (conversion up, risk down, B05/B06 gone,
significant) is reproduced; the absolute Before figure is a synthetic-data property. New blockers surface once the walls are gone
(B10 checkout validation, B07 overlays), which is realistic: the fixes reveal the next layer. Humans also gain in the synthetic model
(the fixes help them too), so the control is not flat; read the lift against it.
