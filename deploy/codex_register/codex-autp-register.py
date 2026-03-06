#!/usr/bin/env python
import argparse
import base64
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional, Set


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--proxy")
    parser.add_argument("--auth-url")
    parser.add_argument("--session-id")
    parser.add_argument("--help", action="help")
    return parser.parse_args()


def as_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def as_int(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    raw = as_str(value)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def decode_jwt_payload(raw_token: str) -> dict:
    token = as_str(raw_token)
    if not token or token.count(".") < 2:
        return {}
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")).decode("utf-8"))
    except Exception:
        return {}


def normalize_id_token(raw_value) -> tuple[str, dict]:
    if isinstance(raw_value, dict):
        raw_jwt = as_str(raw_value.get("raw_jwt") or raw_value.get("raw") or raw_value.get("token"))
        claims = decode_jwt_payload(raw_jwt)
        for key in ("email", "sub", "exp"):
            if raw_value.get(key) is not None and claims.get(key) is None:
                claims[key] = raw_value.get(key)
        return raw_jwt, claims
    raw_jwt = as_str(raw_value)
    return raw_jwt, decode_jwt_payload(raw_jwt)


def auth_file_candidates() -> List[Path]:
    candidates: List[Path] = []
    env_file = as_str(os.getenv("CODEX_AUTH_FILE"))
    if env_file:
        path = Path(env_file)
        if path.is_file():
            candidates.append(path)

    auth_dir = Path(as_str(os.getenv("CODEX_AUTH_DIR")) or "/app/codex-auth")
    if auth_dir.is_dir():
        for path in sorted(auth_dir.rglob("*.json")):
            if not path.is_file():
                continue
            if "/tokens/" in path.as_posix():
                continue
            candidates.append(path)

    deduped: List[Path] = []
    seen: Set[str] = set()
    for path in candidates:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def normalize_token_payload(data: dict, source_file: Path) -> Optional[dict]:
    access_token = as_str(data.get("access_token"))
    refresh_token = as_str(data.get("refresh_token"))
    id_token_raw, claims = normalize_id_token(data.get("id_token"))
    auth_claims = claims.get("https://api.openai.com/auth")
    if not isinstance(auth_claims, dict):
        auth_claims = {}

    email = as_str(data.get("email")) or as_str(claims.get("email"))
    account_id = (
        as_str(data.get("account_id"))
        or as_str(auth_claims.get("chatgpt_account_id"))
        or as_str(auth_claims.get("user_id"))
    )
    expired = (
        as_int(data.get("expired"))
        or as_int(data.get("expires_at"))
        or as_int(claims.get("exp"))
    )

    if not any([access_token, refresh_token, id_token_raw, email, account_id]):
        return None

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "id_token": id_token_raw,
        "email": email,
        "account_id": account_id,
        "expired": expired,
        "source": as_str(data.get("source")) or "codex-auth-json",
        "auth_file": str(source_file),
    }


def parse_auth_file(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[codex-autp-register] failed to parse {path}: {exc}", flush=True)
        return None

    if isinstance(data, dict) and isinstance(data.get("tokens"), dict):
        tokens = dict(data.get("tokens") or {})
        tokens.setdefault("source", "codex-auth-json")
        return normalize_token_payload(tokens, path)

    if isinstance(data, dict):
        return normalize_token_payload(data, path)

    return None


def write_token_files(tokens_dir: Path, payloads: List[dict]) -> int:
    tokens_dir.mkdir(parents=True, exist_ok=True)
    for old_file in tokens_dir.glob("*.json"):
        try:
            old_file.unlink()
        except OSError:
            pass

    written = 0
    for payload in payloads:
        source_key = payload.get("email") or payload.get("account_id") or payload.get("auth_file") or str(time.time())
        digest = hashlib.sha1(as_str(source_key).encode("utf-8")).hexdigest()[:12]
        out_path = tokens_dir / f"token-{digest}.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        written += 1
    return written


def call_browser_register(args: argparse.Namespace) -> List[dict]:
    endpoint = as_str(os.getenv("CODEX_BROWSER_REGISTER_URL"))
    if not endpoint:
        print("[codex-autp-register] CODEX_BROWSER_REGISTER_URL not configured", flush=True)
        return []

    payload = {
        "auth_url": as_str(args.auth_url),
        "session_id": as_str(args.session_id),
        "proxy": as_str(args.proxy),
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"[codex-autp-register] browser register failed: {exc.code} {body}", flush=True)
        return []
    except urllib.error.URLError as exc:
        print(f"[codex-autp-register] browser register unreachable: {exc}", flush=True)
        return []

    try:
        data = json.loads(body) if body else {}
    except Exception as exc:
        print(f"[codex-autp-register] invalid browser register response: {exc}", flush=True)
        return []

    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return [item for item in data["items"] if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def main() -> int:
    args = parse_args()

    tokens_dir = Path("tokens")
    if as_str(args.auth_url):
        payloads = call_browser_register(args)
        written = write_token_files(tokens_dir, payloads)
        print(
            f"[codex-autp-register] oauth automation wrote {written} callback file(s)",
            flush=True,
        )
        return 0

    auth_files = auth_file_candidates()
    if not auth_files:
        print("[codex-autp-register] no Codex auth files found", flush=True)
        write_token_files(tokens_dir, [])
        return 0

    payloads: List[dict] = []
    for path in auth_files:
        payload = parse_auth_file(path)
        if payload is None:
            continue
        payloads.append(payload)

    written = write_token_files(tokens_dir, payloads)
    print(
        f"[codex-autp-register] discovered {len(auth_files)} auth file(s), wrote {written} token file(s)",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
