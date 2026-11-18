"""Client key shared by identification (behavioural runs) and sessionization so both agree on who is who.

A request's key is its cookie; a cookie-less request inherits a cookie seen from the same ip+ua within `attach_s`
seconds (first request of a browser visit precedes Set-Cookie); otherwise the key is ip+ua.
Source relation needs: ts, ip_hash, ua_hash, cookie.
"""

from __future__ import annotations


def keyed_sql(source: str, attach_s: int) -> str:
    """SQL producing every column of `source` plus `ckey`."""
    return f"""
        WITH w AS (
          SELECT *,
            last_value(CASE WHEN cookie IS NOT NULL THEN ts END IGNORE NULLS) OVER wp AS prev_ts,
            last_value(cookie IGNORE NULLS) OVER wp AS prev_cookie,
            first_value(CASE WHEN cookie IS NOT NULL THEN ts END IGNORE NULLS) OVER wn AS next_ts,
            first_value(cookie IGNORE NULLS) OVER wn AS next_cookie
          FROM {source}
          WINDOW wp AS (PARTITION BY ip_hash, ua_hash ORDER BY ts ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW),
                 wn AS (PARTITION BY ip_hash, ua_hash ORDER BY ts ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING)
        )
        SELECT * EXCLUDE (prev_ts, prev_cookie, next_ts, next_cookie), COALESCE(
            cookie,
            CASE WHEN prev_ts >= ts - INTERVAL {attach_s} SECOND THEN prev_cookie END,
            CASE WHEN next_ts <= ts + INTERVAL {attach_s} SECOND THEN next_cookie END,
            'ip:' || ip_hash || '|' || ua_hash) AS ckey
        FROM w
    """
