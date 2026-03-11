import argparse
import importlib
import json
import os
from typing import Any, Dict, Tuple

JSONDict = Dict[str, Any]
TARGET_MODEL = "gpt-5.3-codex"


def ensure_dict(value: object) -> JSONDict:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def pg_json(value: Any):
    Json = importlib.import_module("psycopg2.extras").Json
    return Json(value)


def create_db_connection():
    psycopg2 = importlib.import_module("psycopg2")

    host = os.getenv("POSTGRES_HOST", "postgres")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    connect_timeout = int(os.getenv("POSTGRES_CONNECT_TIMEOUT", "5"))
    user = os.getenv("POSTGRES_USER", "")
    password = os.getenv("POSTGRES_PASSWORD", "")
    dbname = os.getenv("POSTGRES_DB", "")

    if not user or not password or not dbname:
        raise RuntimeError("POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB must be set")

    return psycopg2.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        dbname=dbname,
        connect_timeout=connect_timeout,
    )


def rewrite_claude_mapping(mapping: object) -> Tuple[JSONDict, bool]:
    src = ensure_dict(mapping)
    if not src:
        return {}, False

    updated = dict(src)
    changed = False
    for key in list(updated.keys()):
        if str(key).startswith("claude-") and updated[key] != TARGET_MODEL:
            updated[key] = TARGET_MODEL
            changed = True

    return updated, changed


def rewrite_account_payloads(credentials: object, extra: object) -> Tuple[Any, Any, bool]:
    credentials_dict = ensure_dict(credentials)
    extra_dict = ensure_dict(extra)

    credentials_mapping, credentials_changed = rewrite_claude_mapping(credentials_dict.get("model_mapping"))
    extra_mapping, extra_changed = rewrite_claude_mapping(extra_dict.get("codex_auto_register_model_mapping"))

    next_credentials: Any = dict(credentials) if isinstance(credentials, dict) else credentials
    if credentials_changed:
        next_credentials = dict(credentials_dict)
        next_credentials["model_mapping"] = credentials_mapping

    next_extra: Any = dict(extra) if isinstance(extra, dict) else extra
    if extra_changed:
        next_extra = dict(extra_dict)
        next_extra["codex_auto_register_model_mapping"] = extra_mapping

    return next_credentials, next_extra, credentials_changed or extra_changed


def run_migration(conn, *, apply: bool, out=print) -> Dict[str, int]:
    counters = {
        "scanned": 0,
        "changed": 0,
        "unchanged": 0,
        "updated": 0,
    }

    cur = conn.cursor()

    previous_autocommit = getattr(conn, "autocommit", None)
    if apply and previous_autocommit is not None:
        conn.autocommit = False

    try:
        cur.execute(
            "SELECT id, credentials, extra FROM accounts WHERE platform = 'openai' AND type = 'oauth' ORDER BY id"
        )
        rows = cur.fetchall()

        for row_id, credentials, extra in rows:
            counters["scanned"] += 1
            next_credentials, next_extra, changed = rewrite_account_payloads(credentials, extra)
            if not changed:
                counters["unchanged"] += 1
                continue

            counters["changed"] += 1
            if apply:
                cur.execute(
                    "UPDATE accounts SET credentials = %s, extra = %s, updated_at = NOW() WHERE id = %s",
                    (pg_json(next_credentials), pg_json(next_extra), row_id),
                )
                counters["updated"] += 1

        if apply:
            conn.commit()
    except Exception:
        if apply:
            conn.rollback()
        raise
    finally:
        if apply and previous_autocommit is not None:
            conn.autocommit = previous_autocommit

    out(
        "scanned={scanned} changed={changed} unchanged={unchanged} updated={updated}".format(
            **counters
        )
    )
    return counters


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-time migration: rewrite claude-* model mappings to gpt-5.2-codex"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="scan and report only")
    mode.add_argument("--apply", action="store_true", help="apply updates")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    apply = bool(args.apply)

    conn = create_db_connection()
    try:
        run_migration(conn, apply=apply)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
