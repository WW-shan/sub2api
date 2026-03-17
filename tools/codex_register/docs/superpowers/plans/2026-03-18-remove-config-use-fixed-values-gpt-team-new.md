# Remove config.yaml and Use Fixed Values in gpt-team-new.py Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `gpt-team-new.py` run without `config.yaml` by hardcoding all runtime settings as in-file constants.

**Architecture:** Keep the current business flow unchanged and only replace configuration source. Delete the config loader (`_load_config`/`_cfg`) and yaml dependency, then define one explicit constant block for all currently configured values. Validate by compile + symbol checks to ensure no config references remain.

**Tech Stack:** Python 3, requests, existing single-file runtime script (`gpt-team-new.py`).

---

## File Structure / Responsibility Map

- Modify: `gpt-team-new.py`
  - Remove config file loading and yaml import
  - Add/keep fixed constants for all runtime values
  - Update startup logs to indicate fixed constants
- Optional test-only checks via command line (no new test file required for this focused refactor)

---

## Chunk 1: Remove config dependency and hardcode constants

### Task 1: Remove yaml/config loader and keep fixed constants only

**Files:**
- Modify: `gpt-team-new.py`

- [ ] **Step 1: Write a failing verification command (pre-change) to prove config symbols exist**

Run:
`python -c "import pathlib; s=pathlib.Path('gpt-team-new.py').read_text(encoding='utf-8'); assert '_load_config' not in s"`

Expected: FAIL (because `_load_config` currently exists).

- [ ] **Step 2: Remove config loading and yaml import**

Edit `gpt-team-new.py`:
- delete `import yaml`
- delete `_CONFIG_FILE`
- delete `_load_config()`
- delete `_cfg = _load_config()`

- [ ] **Step 3: Replace all `_cfg[...]`-derived assignments with fixed constants**

Set explicit in-file constants for:
- `TOTAL_ACCOUNTS`
- `MAIL_WORKER_BASE_URL`
- `MAIL_WORKER_TOKEN`
- `MAIL_DOMAIN`
- `MAIL_POLL_SECONDS`
- `MAIL_POLL_MAX_ATTEMPTS`
- `CLI_PROXY_API_BASE`
- `CLI_PROXY_PASSWORD`
- `CPA_UPLOAD_ENABLED`
- `ACCOUNTS_FILE`
- `INVITE_TRACKER_FILE`
- `TEAMS`

- [ ] **Step 4: Update startup logs to no longer mention config file path**

Replace log line that references `_CONFIG_FILE` with a fixed-config message.

- [ ] **Step 5: Run compile check**

Run:
`python -m py_compile gpt-team-new.py`

Expected: PASS (no output).

- [ ] **Step 6: Commit**

```bash
git add gpt-team-new.py
git commit -m "refactor: remove config yaml dependency and hardcode runtime values"
```

---

## Chunk 2: Verify no config references remain

### Task 2: Enforce no legacy config symbols

**Files:**
- Modify: `gpt-team-new.py` (only if cleanup needed)

- [ ] **Step 1: Run symbol checks for removed config/yaml artifacts**

Run:
- `python -c "import pathlib; s=pathlib.Path('gpt-team-new.py').read_text(encoding='utf-8'); assert '_cfg' not in s"`
- `python -c "import pathlib; s=pathlib.Path('gpt-team-new.py').read_text(encoding='utf-8'); assert '_load_config' not in s"`
- `python -c "import pathlib; s=pathlib.Path('gpt-team-new.py').read_text(encoding='utf-8'); assert 'config.yaml' not in s"`
- `python -c "import pathlib; s=pathlib.Path('gpt-team-new.py').read_text(encoding='utf-8'); assert 'import yaml' not in s"`

Expected: all PASS.

- [ ] **Step 2: Run final syntax check again**

Run:
`python -m py_compile gpt-team-new.py`

Expected: PASS.

- [ ] **Step 3: Run lightweight smoke execution (optional, safe path)**

Run:
`python gpt-team-new.py`

Expected: script starts with fixed config banner and proceeds according to hardcoded values.

- [ ] **Step 4: Commit any final cleanup**

```bash
git add gpt-team-new.py
git commit -m "chore: finalize fixed-value configuration mode in gpt-team-new"
```

---

## Notes for implementer

- Do not introduce compatibility shims for old config flow.
- Do not keep hidden `_cfg` fallback paths.
- Keep solution minimal (YAGNI): this change is source-of-config only, not workflow redesign.
