-- AgentLens DuckDB schema (PRD section 21). Idempotent: safe to run on every start.

CREATE TABLE IF NOT EXISTS requests (
  request_id VARCHAR PRIMARY KEY,
  ts TIMESTAMP,
  method VARCHAR, host VARCHAR, path VARCHAR, query VARCHAR,
  status INTEGER, bytes_out BIGINT, duration_ms INTEGER,
  ip_hash VARCHAR, ip_prefix VARCHAR,
  user_agent VARCHAR, ua_hash VARCHAR, referer VARCHAR, accept VARCHAR, accept_language VARCHAR,
  sec_ch_ua VARCHAR, sec_fetch_site VARCHAR, sec_fetch_mode VARCHAR, sec_fetch_dest VARCHAR,
  has_signature BOOLEAN, signature_status VARCHAR, signature_agent VARCHAR,
  cookie_sid_hash VARCHAR, is_asset BOOLEAN, event_type VARCHAR, page_type VARCHAR, error_code VARCHAR,
  identity_tier VARCHAR, operator VARCHAR, agent_name VARCHAR, agent_class VARCHAR,
  identity_confidence DOUBLE, suspicion_score DOUBLE,
  session_id VARCHAR, ingested_at TIMESTAMP, source_file VARCHAR,
  unit_price DOUBLE, product_id VARCHAR
);
-- M3: cart unit price / product id (meta.unit_price, meta.product_id) feed the B15 price-mismatch rule.
ALTER TABLE requests ADD COLUMN IF NOT EXISTS unit_price DOUBLE;
ALTER TABLE requests ADD COLUMN IF NOT EXISTS product_id VARCHAR;

-- Raw signature headers are needed for verification; kept in a side table so `requests` stays lean.
CREATE TABLE IF NOT EXISTS request_signatures (
  request_id VARCHAR PRIMARY KEY,
  signature VARCHAR, signature_input VARCHAR, signature_agent VARCHAR, method VARCHAR, authority VARCHAR, path VARCHAR
);

CREATE TABLE IF NOT EXISTS sessions (
  session_id VARCHAR PRIMARY KEY,
  session_key VARCHAR,
  start_ts TIMESTAMP, end_ts TIMESTAMP, duration_s DOUBLE,
  request_count INTEGER, page_count INTEGER, has_beacon BOOLEAN,
  identity_tier VARCHAR, operator VARCHAR, agent_name VARCHAR, agent_class VARCHAR, identity_confidence DOUBLE,
  entry_page VARCHAR, exit_page VARCHAR,
  max_stage VARCHAR, converted BOOLEAN, order_id VARCHAR, order_value DOUBLE,
  terminal_blocker_id VARCHAR, blocker_confidence DOUBLE, diagnosis_method VARCHAR
);

CREATE TABLE IF NOT EXISTS session_stages (
  session_id VARCHAR, stage_id VARCHAR, first_reached_ts TIMESTAMP
);

-- M3 funnel aggregates. day IS NULL = whole window. sessions_reached counts sessions with max_stage >= stage
-- (cumulative); step_conv = reached / reached at the previous stage (S1: reached / total); dropped = previous - reached.
CREATE TABLE IF NOT EXISTS funnel_stats (
  segment_type VARCHAR, segment VARCHAR, day DATE, stage_id VARCHAR,
  sessions_reached INTEGER, sessions_total INTEGER, step_conv DOUBLE, overall_conv DOUBLE, dropped INTEGER
);

CREATE TABLE IF NOT EXISTS blocker_hits (
  session_id VARCHAR, blocker_id VARCHAR, stage_id VARCHAR, confidence DOUBLE,
  is_terminal BOOLEAN, evidence_json VARCHAR
);

CREATE TABLE IF NOT EXISTS site_checks (
  check_id VARCHAR PRIMARY KEY, run_ts TIMESTAMP, check_name VARCHAR, target VARCHAR,
  result VARCHAR, details_json VARCHAR
);

CREATE TABLE IF NOT EXISTS replays (
  replay_id VARCHAR PRIMARY KEY, blocker_id VARCHAR, source_session_id VARCHAR, mode VARCHAR,
  status VARCHAR, started_at TIMESTAMP, finished_at TIMESTAMP, steps_json VARCHAR,
  evidence_dir VARCHAR, verdict_explanation VARCHAR
);

CREATE TABLE IF NOT EXISTS impact (
  run_id VARCHAR, window_start TIMESTAMP, window_end TIMESTAMP, blocker_id VARCHAR, stage_id VARCHAR,
  sessions_blocked INTEGER, p_stage DOUBLE,
  recoverable_low DOUBLE, recoverable_base DOUBLE, recoverable_high DOUBLE,
  aov DOUBLE, risk_low DOUBLE, risk_base DOUBLE, risk_high DOUBLE, low_confidence BOOLEAN
);

CREATE TABLE IF NOT EXISTS impact_assumptions (
  run_id VARCHAR, blocker_id VARCHAR, p_source VARCHAR, window_days DOUBLE, k DOUBLE, aov_source VARCHAR,
  r_low DOUBLE, r_base DOUBLE, r_high DOUBLE
);

CREATE TABLE IF NOT EXISTS recommendations (
  rec_id VARCHAR PRIMARY KEY, run_id VARCHAR, blocker_id VARCHAR, title VARCHAR, body VARCHAR,
  effort VARCHAR, owner VARCHAR, priority_score DOUBLE, status VARCHAR, fixed_annotation_id VARCHAR
);

CREATE TABLE IF NOT EXISTS annotations (
  annotation_id VARCHAR PRIMARY KEY, ts TIMESTAMP, type VARCHAR, label VARCHAR, details_json VARCHAR
);

CREATE TABLE IF NOT EXISTS orders (
  order_id VARCHAR PRIMARY KEY, ts TIMESTAMP, session_id VARCHAR, cookie_sid_hash VARCHAR,
  order_value DOUBLE, payment_method VARCHAR, request_id VARCHAR
);

CREATE TABLE IF NOT EXISTS key_cache (
  signature_agent VARCHAR PRIMARY KEY, fetched_at TIMESTAMP, keys_json VARCHAR, status VARCHAR
);

CREATE TABLE IF NOT EXISTS ingest_state (
  source_file VARCHAR PRIMARY KEY, last_offset BIGINT, last_ingested_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ingest_errors (
  source_file VARCHAR, line_no BIGINT, error VARCHAR, raw_line VARCHAR, ts TIMESTAMP
);

-- Evaluation only. Diagnosis, identification and impact code must never read this table (PRD 12.6).
CREATE TABLE IF NOT EXISTS ground_truth (
  run_id VARCHAR, synthetic_session_id VARCHAR, persona VARCHAR, expected_tier VARCHAR,
  operator VARCHAR, agent_class VARCHAR, task VARCHAR, toggles_json VARCHAR,
  blocker_hit VARCHAR, stage_of_failure VARCHAR, converted BOOLEAN
);

CREATE TABLE IF NOT EXISTS runs (
  run_id VARCHAR PRIMARY KEY, started_at TIMESTAMP, finished_at TIMESTAMP,
  steps_json VARCHAR, status VARCHAR, counts_json VARCHAR
);
