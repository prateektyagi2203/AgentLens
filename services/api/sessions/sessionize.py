"""C5 sessionization (PRD 12.1): requests -> sessions, set-based in DuckDB. Full recompute, idempotent.

Key priority: verified/declared/internal agents use operator+agent+ip+ua (agents drop cookies); otherwise the client key
(cookie, or ip+ua). Inactivity timeouts: 10 min for agent tiers, 30 min for humans.
"""

from __future__ import annotations

from typing import Any

import duckdb

from .. import db, settings
from ..clientkey import keyed_sql

ORDER_COOKIE_WINDOW_MIN = 60
AGENT_TIERS = ("verified", "declared", "internal", "suspected")


def sessionize(con: duckdb.DuckDBPyConnection, ctx: Any = None) -> dict[str, int]:
    """Rebuild `sessions`, set `requests.session_id`, link orders. The caller owns the transaction."""
    cfg = settings.load_yaml("identification").get("sessions", {})
    t_human = int(cfg.get("timeout_min_human", 30))
    t_agent = int(cfg.get("timeout_min_agent", 10))
    attach_s = int(cfg.get("cookie_attach_s", 120))
    agent_sql = ", ".join(f"'{t}'" for t in AGENT_TIERS)

    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE _sreq AS
        SELECT request_id, ts, COALESCE(ip_hash, '') AS ip_hash, COALESCE(ua_hash, '') AS ua_hash,
               cookie_sid_hash AS cookie, COALESCE(identity_tier, 'human') AS tier, operator, agent_name, agent_class,
               identity_confidence AS conf, page_type, path, is_asset
        FROM requests
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _skey AS
        WITH k AS ({keyed_sql("_sreq", attach_s)}),
        s AS (
          SELECT *, CASE WHEN tier IN ('verified', 'declared', 'internal')
                         THEN COALESCE(operator, '') || '|' || COALESCE(agent_name, '') || '|' || ip_hash || '|' || ua_hash
                         ELSE ckey END AS skey,
                 CASE tier WHEN 'internal' THEN 50 WHEN 'verified' THEN 40 WHEN 'declared' THEN 30
                           WHEN 'suspected' THEN 20 ELSE 10 END + COALESCE(conf, 0) AS rk
          FROM k
        ), g AS (
          SELECT *, lag(ts) OVER (PARTITION BY skey ORDER BY ts) AS prev_t FROM s
        )
        SELECT *, sum(CASE WHEN prev_t IS NULL
                           OR ts - prev_t > CASE WHEN tier IN ({agent_sql}) THEN INTERVAL {t_agent} MINUTE
                                                 ELSE INTERVAL {t_human} MINUTE END
                           THEN 1 ELSE 0 END) OVER (PARTITION BY skey ORDER BY ts ROWS UNBOUNDED PRECEDING) AS seq
        FROM g
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE _sess AS
        SELECT substr(md5(skey || '@' || CAST(min(ts) AS VARCHAR)), 1, 16) AS session_id, skey AS session_key, seq,
               min(ts) AS start_ts, max(ts) AS end_ts, epoch(max(ts) - min(ts)) AS duration_s,
               count(*)::INTEGER AS request_count,
               (count(*) FILTER (WHERE page_type NOT IN ('asset', 'beacon') OR page_type IS NULL))::INTEGER AS page_count,
               COALESCE(bool_or(page_type = 'beacon'), false) AS has_beacon,
               arg_max(tier, rk) AS identity_tier, arg_max(operator, rk) AS operator,
               arg_max(agent_name, rk) AS agent_name, arg_max(agent_class, rk) AS agent_class,
               arg_max(conf, rk) AS identity_confidence,
               arg_min(path, ts) FILTER (WHERE page_type NOT IN ('asset', 'beacon')) AS entry_page,
               arg_max(path, ts) FILTER (WHERE page_type NOT IN ('asset', 'beacon')) AS exit_page
        FROM _skey GROUP BY skey, seq
        """
    )

    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE _req_sess AS
        SELECT k.request_id, s.session_id
        FROM _skey k JOIN _sess s ON s.session_key = k.skey AND s.seq = k.seq
        """
    )
    con.execute("UPDATE requests SET session_id = m.session_id FROM _req_sess m WHERE requests.request_id = m.request_id")

    con.execute("DELETE FROM sessions")
    con.execute(
        """
        INSERT INTO sessions (session_id, session_key, start_ts, end_ts, duration_s, request_count, page_count,
                              has_beacon, identity_tier, operator, agent_name, agent_class, identity_confidence,
                              entry_page, exit_page, converted)
        SELECT session_id, session_key, start_ts, end_ts, duration_s, request_count, page_count, has_beacon,
               identity_tier, operator, agent_name, agent_class, identity_confidence, entry_page, exit_page, false
        FROM _sess
        """
    )
    linked = _link_orders(con)
    n_sessions = db.one(con, "SELECT count(*) FROM sessions")
    return {"sessions": int(n_sessions[0]) if n_sessions else 0, **linked}


def _link_orders(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Orders -> sessions: by the checkout request that created them, else the cookie's nearest preceding request."""
    con.execute(
        "UPDATE orders SET session_id = r.session_id FROM requests r WHERE orders.request_id = r.request_id"
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _ord_link AS
        SELECT o.order_id, r.session_id
        FROM (SELECT order_id, ts, cookie_sid_hash FROM orders
              WHERE session_id IS NULL AND cookie_sid_hash IS NOT NULL) o
        ASOF JOIN (SELECT ts, cookie_sid_hash, session_id FROM requests
                   WHERE cookie_sid_hash IS NOT NULL AND session_id IS NOT NULL) r
          ON o.cookie_sid_hash = r.cookie_sid_hash AND o.ts >= r.ts
        WHERE o.ts - r.ts <= INTERVAL {ORDER_COOKIE_WINDOW_MIN} MINUTE
        """
    )
    con.execute("UPDATE orders SET session_id = l.session_id FROM _ord_link l WHERE orders.order_id = l.order_id")
    con.execute(
        """
        UPDATE sessions SET converted = true, order_id = o.order_id, order_value = o.total
        FROM (SELECT session_id, arg_min(order_id, ts) AS order_id, sum(order_value) AS total
              FROM orders WHERE session_id IS NOT NULL GROUP BY session_id) o
        WHERE sessions.session_id = o.session_id
        """
    )
    row = db.one(con, "SELECT count(*) FILTER (WHERE session_id IS NOT NULL), count(*) FROM orders")
    return {"orders_linked": int(row[0]) if row else 0, "orders_total": int(row[1]) if row else 0}
