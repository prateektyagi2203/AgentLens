"""C3 ingestion: native JSONL and nginx combined logs -> DuckDB `requests` (PRD section 10).

This package reads only an allow-list of `meta` keys, so synthetic-run link fields never reach storage (PRD 12.6).
"""

from .loader import IngestResult, ingest_file, ingest_path

__all__ = ["IngestResult", "ingest_file", "ingest_path"]
