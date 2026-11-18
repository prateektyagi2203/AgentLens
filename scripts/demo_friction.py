"""Set the demo store's friction toggles to the Before or After state (PRD Appendix C). Used by `tasks.ps1 demo` and `make demo`.

Usage: python scripts/demo_friction.py before|after
The store applies edits to apps/store/config/friction.json without a restart. Restore the file afterwards with
`git checkout apps/store/config/friction.json`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FILE = Path(__file__).resolve().parents[1] / "apps" / "store" / "config" / "friction.json"
BEFORE_ON = {"F03", "F05", "F06", "F07", "F09", "F10"}
AFTER_OFF = {"F03", "F05", "F06"}


def main(state: str) -> None:
    if state not in ("before", "after"):
        raise SystemExit(__doc__)
    data = json.loads(FILE.read_text(encoding="utf-8"))
    on = BEFORE_ON - (AFTER_OFF if state == "after" else set())
    data["toggles"] = {k: k in on for k in data["toggles"]}
    FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
