import argparse
import importlib
import json
import time
import urllib.request
from typing import Any, Callable, Dict, Iterable, Set

JSONDict = Dict[str, Any]


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def post_action(base_url: str, path: str) -> JSONDict:
    req = urllib.request.Request(
        _join_url(base_url, path),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8")
    return json.loads(raw or "{}")


def fetch_status(base_url: str) -> JSONDict:
    with urllib.request.urlopen(_join_url(base_url, "/status"), timeout=15) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8")
    return json.loads(raw or "{}")


def wait_for_phase(
    base_url: str,
    *,
    target_phases: Set[str],
    timeout_seconds: int,
    interval_seconds: int,
) -> JSONDict:
    deadline = time.monotonic() + max(0, int(timeout_seconds))
    interval = max(1, int(interval_seconds))

    while True:
        status = fetch_status(base_url)
        phase = str(status.get("job_phase") or "")
        if phase in target_phases:
            return status
        if time.monotonic() >= deadline:
            raise RuntimeError(f"timeout waiting for phases {sorted(target_phases)}, last phase={phase}")
        time.sleep(interval)


def create_db_connection():
    service = importlib.import_module("tools.codex_register.codex_register_service")
    return service.create_db_connection()


def verify_database_state(conn, *, min_children: int, parent_email: str = "") -> JSONDict:
    cur = conn.cursor()
    try:
        normalized_parent_email = str(parent_email or "").strip()
        if normalized_parent_email:
            cur.execute(
                "SELECT email, plan_type, organization_id, workspace_id, workspace_reachable, members_page_accessible "
                "FROM codex_register_accounts "
                "WHERE source = 'codex-register' AND codex_register_role = 'parent' AND email = %s "
                "ORDER BY created_at DESC LIMIT 1",
                (normalized_parent_email,),
            )
        else:
            cur.execute(
                "SELECT email, plan_type, organization_id, workspace_id, workspace_reachable, members_page_accessible "
                "FROM codex_register_accounts "
                "WHERE source = 'codex-register' AND codex_register_role = 'parent' "
                "ORDER BY created_at DESC LIMIT 1"
            )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("parent record not found")

        parent_email = str(row[0] or "").strip()
        plan_type = str(row[1] or "").strip().lower()
        organization_id = str(row[2] or "").strip()
        workspace_id = str(row[3] or "").strip()
        workspace_reachable = row[4]
        members_page_accessible = row[5]

        if not plan_type or not organization_id or not workspace_id:
            raise RuntimeError("parent metadata incomplete")
        if workspace_reachable is False:
            raise RuntimeError("parent workspace unreachable")
        if members_page_accessible is False:
            raise RuntimeError("parent members page inaccessible")

        cur.execute(
            "SELECT COUNT(*) FROM codex_register_accounts "
            "WHERE source = 'codex-register' AND codex_register_role = 'child' "
            "AND plan_type = %s AND organization_id = %s AND workspace_id = %s "
            "AND created_at >= NOW() - INTERVAL '30 minutes'",
            (plan_type, organization_id, workspace_id),
        )
        child_register_count = int((cur.fetchone() or [0])[0] or 0)
        if child_register_count < max(1, int(min_children)):
            raise RuntimeError(
                f"insufficient child register records: expected>={min_children}, got={child_register_count}"
            )

        cur.execute(
            "SELECT COUNT(*) FROM codex_register_accounts "
            "WHERE source = 'codex-register' AND codex_register_role = 'child' "
            "AND plan_type = %s AND organization_id = %s AND workspace_id = %s "
            "AND COALESCE(refresh_token, '') <> '' AND COALESCE(access_token, '') <> '' AND COALESCE(account_id, '') <> '' "
            "AND created_at >= NOW() - INTERVAL '30 minutes'",
            (plan_type, organization_id, workspace_id),
        )
        child_invite_accept_count = int((cur.fetchone() or [0])[0] or 0)
        if child_invite_accept_count < max(1, int(min_children)):
            raise RuntimeError(
                f"child invite acceptance incomplete: expected>={min_children}, got={child_invite_accept_count}"
            )

        cur.execute(
            "SELECT COUNT(*) FROM accounts "
            "WHERE platform = 'openai' AND type = 'oauth' "
            "AND credentials ->> 'plan_type' = %s "
            "AND credentials ->> 'organization_id' = %s "
            "AND COALESCE(credentials ->> 'account_id', '') <> '' "
            "AND extra ->> 'codex_register_role' = 'child'",
            (plan_type, organization_id),
        )
        child_pool_count = int((cur.fetchone() or [0])[0] or 0)
        if child_pool_count < max(1, int(min_children)):
            raise RuntimeError(f"business login binding incomplete: expected>={min_children}, got={child_pool_count}")

        return {
            "parent_email": parent_email,
            "plan_type": plan_type,
            "organization_id": organization_id,
            "workspace_id": workspace_id,
            "child_register_count": child_register_count,
            "child_invite_accept_count": child_invite_accept_count,
            "child_pool_count": child_pool_count,
        }
    finally:
        try:
            cur.close()
        except Exception:  # noqa: BLE001
            pass


def run_smoke_flow(args: argparse.Namespace, *, out: Callable[[str], None] = print) -> int:
    post_action(args.base_url, "/enable")
    waiting = wait_for_phase(
        args.base_url,
        target_phases={"waiting_manual:parent_upgrade"},
        timeout_seconds=args.timeout,
        interval_seconds=args.interval,
    )
    out(f"parent waiting phase reached: {waiting.get('job_phase')}")

    post_action(args.base_url, "/resume")
    completed = wait_for_phase(
        args.base_url,
        target_phases={"completed"},
        timeout_seconds=args.timeout,
        interval_seconds=args.interval,
    )
    out(f"resume completed phase reached: {completed.get('job_phase')}")

    conn = create_db_connection()
    try:
        summary = verify_database_state(
            conn,
            min_children=args.min_children,
            parent_email=args.parent_email,
        )
    finally:
        conn_close = getattr(conn, "close", None)
        if callable(conn_close):
            conn_close()

    out(f"db verification passed: {summary}")
    return 0


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Codex register end-to-end smoke test")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000", help="Codex register service base URL")
    parser.add_argument("--timeout", type=int, default=600, help="Timeout seconds for each phase wait")
    parser.add_argument("--interval", type=int, default=5, help="Polling interval seconds")
    parser.add_argument("--min-children", type=int, default=1, help="Minimum child records required")
    parser.add_argument("--parent-email", default="", help="Expected parent email for DB matching")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run_smoke_flow(args)
    except Exception as exc:  # noqa: BLE001
        print(f"smoke test failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
