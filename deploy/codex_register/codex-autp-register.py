#!/usr/bin/env python
import json
import sys
import time
from pathlib import Path


def main() -> int:
    tokens_dir = Path("tokens")
    tokens_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "access_token": "",
        "refresh_token": "",
        "id_token": "",
        "account_id": "",
        "expired": int(time.time()) + 3600,
        "source": "codex-auto-register-stub",
    }

    ts = int(time.time())
    out_path = tokens_dir / f"token-{ts}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    print(f"[codex-autp-register] wrote stub token file: {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
