"""Start / stop the real Desi Threads store on a free port for integration tests (kills only its own PID tree)."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[2]
STORE = REPO / "apps" / "store"
ADMIN_PASSWORD = "pw-replay-test"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class StoreServer:
    def __init__(self, work_dir: Path, port: int | None = None) -> None:
        self.port = port or free_port()
        self.work_dir = work_dir
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen[bytes] | None = None

    def start(self, timeout_s: float = 90.0) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        friction = self.work_dir / "friction.json"
        shutil.copyfile(STORE / "config" / "friction.json", friction)
        env = {
            **os.environ, "PORT": str(self.port), "HOST": "127.0.0.1", "NODE_ENV": "production",
            "AGENTLENS_DATA_DIR": str(self.work_dir / "data"), "AGENTLENS_FRICTION_FILE": str(friction),
            "AGENTLENS_ADMIN_PASSWORD": ADMIN_PASSWORD, "AGENTLENS_IP_SALT": "replay-test",
        }  # fmt: skip
        env.pop("DEMO_MODE", None)
        self.proc = subprocess.Popen(
            ["node", "server.mjs"], cwd=STORE, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("store exited during startup")
            try:
                if httpx.get(f"{self.base_url}/robots.txt", timeout=2).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.5)
        self.stop()
        raise RuntimeError("store did not become ready")

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)], capture_output=True, check=False)
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        self.proc = None

    def set_friction(self, on: set[str] | list[str], note: str = "replay-test") -> None:
        toggles = {f"F{i:02d}": f"F{i:02d}" in set(on) for i in range(1, 17)}
        r = httpx.post(
            f"{self.base_url}/api/admin/friction", headers={"x-admin-password": ADMIN_PASSWORD},
            content=json.dumps({"toggles": toggles, "note": note}), timeout=10,
        )  # fmt: skip
        r.raise_for_status()
