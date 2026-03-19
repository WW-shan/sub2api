# Restore Pre-Merge Codex Register Logic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore all original codex register logic that `5c211aca` changed relative to `5c211aca^1`, while keeping later-added capabilities only where they reuse the restored baseline behavior.

**Architecture:** Treat `5c211aca^1` as the authority for all pre-existing parsing, upsert, naming, mapping, and resume-parent semantics. Implement the fix in two layers: first restore the baseline behavior inside `codex_register_service.py` and its directly coupled tests, then reattach loop-runner and other later additions so they call the restored logic instead of preserving merge-regressed behavior.

**Tech Stack:** Python 3, unittest/pytest, git diff against `5c211aca^1..5c211aca`, existing `CodexRegisterService` helpers in `tools/codex_register/codex_register_service.py`.

---

## File map

- Modify: `tools/codex_register/codex_register_service.py`
  - Restore the pre-merge baseline semantics for parsing, `_upsert_account`, helper behavior, and resume-parent post-processing.
  - Keep loop-runner/state additions only where they do not override restored baseline behavior.
- Modify: `tools/codex_register/test_codex_register_service.py`
  - Restore tests and expectations that `5c211aca` changed or deleted.
  - Restore a concrete `ProcessingFlowTests` class so the spec-mandated gate is executable.
  - Keep later loop-runner tests only if they remain valid against restored semantics.

## Restoration checklist artifact

During implementation, maintain a per-hunk checklist in **worker-local execution notes (not a repo file)**. The notes must cover every hunk from:

```bash
git diff 5c211aca^1 5c211aca -- tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
```

Each row must include:
- source file
- hunk summary
- classification (`restore` / `keep` / `adapt`)
- one-line reason
- final resolution status

This artifact is mandatory review evidence for the spec’s checklist requirement, but it is not part of repo scope and should not be committed unless the user explicitly asks.

## Task 1: Build the restoration checklist from the merge diff

**Files:**
- Modify: `tools/codex_register/codex_register_service.py`
- Modify: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Generate the target diff inventory**

Run:

```bash
git diff 5c211aca^1 5c211aca -- tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
```

Record each hunk in the worker-local checklist as one of:
- `restore`
- `keep`
- `adapt`

For **every** hunk, also record a one-line reason explaining why that classification is correct.

Expected: a finite checklist covering every hunk in both files, with a reason attached to each row.

- [ ] **Step 2: Mark regression hunks in the test file first**

Identify the test expectations that `5c211aca` changed away from the baseline, including the deleted/changed protections around:

```python
self.assertEqual(insert_account_params[0], "free@example.com")
self.assertEqual(credentials["model_mapping"], expected_model_mapping)
```

Expected checklist entries include the removed tests for:
- email-missing create rejection
- invalid-email create rejection
- preserving name/model mapping behavior
- update-without-adding-model-mapping behavior

- [ ] **Step 3: Mark regression hunks in the service file**

The checklist must explicitly include at least these service-level regressions:

```python
_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

if not _EMAIL_PATTERN.fullmatch(email):
    return "skipped"

name = email
credentials["model_mapping"] = self._build_model_mapping()
```

and the deleted resume normalization call in `_handle_process_exit()`.

- [ ] **Step 4: Verify the checklist is exhaustive before code changes**

Expected: every diff hunk in both files is classified before implementation starts.

- [ ] **Step 5: Keep the checklist updated as implementation proceeds**

Expected: every completed hunk has a final resolution status in the worker-local checklist.

## Task 2: Restore the baseline test surface in RED state

**Files:**
- Modify: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Reintroduce the missing baseline upsert tests**

Add or restore failing tests equivalent to the `5c211aca^1` baseline protections, including:

```python
def test_upsert_account_skips_create_when_email_missing(self):
    ...

def test_upsert_account_skips_create_when_email_invalid_and_does_not_fallback_to_account_id_name(self):
    ...

def test_upsert_account_updates_existing_when_values_change_preserves_name_and_model_mapping(self):
    ...

def test_upsert_account_updates_existing_without_adding_model_mapping_when_missing(self):
    ...
```

Also restore the insert expectation:

```python
self.assertEqual(insert_account_params[0], "free@example.com")
```

- [ ] **Step 2: Restore a concrete `ProcessingFlowTests` class**

Add or restore:

```python
class ProcessingFlowTests(ServiceTestCase):
    ...
```

This class must own the parsing/upsert/resume flow checks needed by the spec’s mandatory command:

```bash
python -m unittest tools.codex_register.test_codex_register_service.ProcessingFlowTests -v
```

- [ ] **Step 3: Restore the baseline parsing expectations**

If `5c211aca` changed `_parse_account_jsonl_line()` behavior, add failing tests that encode the `5c211aca^1` semantics.

Example skeleton:

```python
def test_parse_account_jsonl_line_rejects_invalid_email_without_account_fallback(self):
    ...
```

- [ ] **Step 4: Run the restored tests to verify they fail for the intended reason**

Run:

```bash
python -m unittest tools.codex_register.test_codex_register_service.UpsertHelperTests -v
python -m unittest tools.codex_register.test_codex_register_service.JsonlParsingTests -v
python -m unittest tools.codex_register.test_codex_register_service.ProcessingFlowTests -v
```

Expected: FAIL on the currently regressed naming, email validation, model mapping, parsing, or resume-flow behavior.

- [ ] **Step 5: Stage test-only changes**

```bash
git add tools/codex_register/test_codex_register_service.py
# No commit yet unless explicitly requested by the user.
```

## Task 3: Restore baseline service semantics in minimal steps

**Files:**
- Modify: `tools/codex_register/codex_register_service.py`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Restore the baseline email validation helper**

Reintroduce the old validation constant and use it in create-path gating:

```python
_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
```

- [ ] **Step 2: Run the email-missing / invalid-email tests**

Run:

```bash
python -m unittest tools.codex_register.test_codex_register_service.UpsertHelperTests.test_upsert_account_skips_create_when_email_missing -v
python -m unittest tools.codex_register.test_codex_register_service.UpsertHelperTests.test_upsert_account_skips_create_when_email_invalid_and_does_not_fallback_to_account_id_name -v
```

Expected: PASS

- [ ] **Step 3: Restore baseline account naming**

Change the create path back to the baseline semantics:

```python
name = email
```

and remove the merge-regressed fallback behavior:

```python
identifier = account_id or email
name = f"codex-{identifier}"
```

- [ ] **Step 4: Re-run the insert naming test**

Run:

```bash
python -m unittest tools.codex_register.test_codex_register_service.UpsertHelperTests.test_upsert_account_inserts_new_account_and_binds_free_groups -v
```

Expected: PASS with the original `name == email` expectation.

- [ ] **Step 5: Restore `_build_model_mapping()` and baseline create-time mapping injection**

Reintroduce the helper and baseline injection point:

```python
def _build_model_mapping(self) -> Dict[str, str]:
    return {
        "gpt-5.4": "gpt-5.4",
        "gpt-5.4-mini": "gpt-5.4-mini",
        "gpt-5.4-nano": "gpt-5.4-nano",
        "gpt-5.4-pro": "gpt-5.4-pro",
        "gpt-5": "gpt-5",
        "gpt-5-mini": "gpt-5-mini",
        "gpt-5-nano": "gpt-5-nano",
        "gpt-5-codex": "gpt-5-codex",
        "gpt-5.3-codex": "gpt-5.3-codex",
        "gpt-5.2-codex": "gpt-5.2-codex",
        "gpt-5.1-codex": "gpt-5.1-codex",
        "gpt-5.1-codex-max": "gpt-5.1-codex-max",
        "gpt-5.1-codex-mini": "gpt-5.1-codex-mini",
        "codex-mini-latest": "codex-mini-latest",
        "claude-opus*": "gpt-5.4",
        "claude-sonnet*": "gpt-5.3-codex",
        "claude-haiku*": "gpt-5.4-mini",
    }

credentials["model_mapping"] = self._build_model_mapping()
```

Do not add new semantics beyond the baseline.

- [ ] **Step 6: Run the model-mapping restoration tests**

Run:

```bash
python -m unittest tools.codex_register.test_codex_register_service.UpsertHelperTests.test_upsert_account_updates_existing_when_values_change_preserves_name_and_model_mapping -v
python -m unittest tools.codex_register.test_codex_register_service.UpsertHelperTests.test_upsert_account_updates_existing_without_adding_model_mapping_when_missing -v
```

Expected: PASS

- [ ] **Step 7: Restore any baseline parsing behavior changed by `5c211aca`**

Update `_parse_account_jsonl_line()` only where the restoration checklist marked a hunk as `restore`.

Expected shape: parsing returns to `5c211aca^1` semantics without removing later independent features.

- [ ] **Step 8: Run all upsert and parsing tests**

Run:

```bash
python -m unittest tools.codex_register.test_codex_register_service.UpsertHelperTests -v
python -m unittest tools.codex_register.test_codex_register_service.JsonlParsingTests -v
python -m unittest tools.codex_register.test_codex_register_service.ProcessingFlowTests -v
```

Expected: PASS

- [ ] **Step 9: Stage service + test changes**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
# No commit yet unless explicitly requested by the user.
```

## Task 4: Restore the baseline resume parent-processing path

**Files:**
- Modify: `tools/codex_register/codex_register_service.py`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Add a failing test that proves resume success uses the baseline parent normalization path**

Restore or add a targeted test around `_handle_process_exit()` proving that `mode == "resume"` success still calls the parent normalization path before final completion.

Example assertion target:

```python
normalized_state = await self._normalize_parent_record_after_resume(...)
state.update(normalized_state)
```

- [ ] **Step 2: Run the targeted resume-parent tests in RED state**

Run:

```bash
python -m unittest tools.codex_register.test_codex_register_service.ProcessingFlowTests -v
```

Expected: FAIL where the current flow still reflects the merge regression.

- [ ] **Step 3: Restore the deleted parent normalization call in `_handle_process_exit()`**

Bring back the baseline call flow after `processing_summary = self._process_accounts_jsonl_records(state)` and before completion handling.

- [ ] **Step 4: Re-run the targeted resume tests**

Run the same command.
Expected: PASS for the baseline parent-processing path.

- [ ] **Step 5: Run the existing parent replacement tests to verify compatibility**

Run:

```bash
python -m unittest tools.codex_register.test_codex_register_service.UpsertHelperTests.test_resume_parent_record_replacement_preserves_metadata_fields -v
python -m unittest tools.codex_register.test_codex_register_service.UpsertHelperTests.test_resume_parent_record_replacement_preserves_existing_parent_password_without_get_tokens_line -v
```

Expected: PASS

- [ ] **Step 6: Stage the resume-path restoration**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
# No commit yet unless explicitly requested by the user.
```

## Task 5: Reattach later-added features without keeping merge-regressed semantics

**Files:**
- Modify: `tools/codex_register/codex_register_service.py`
- Modify: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Review every checklist item marked `keep` or `adapt`**

Confirm each later-added feature either:
- does not touch restored semantics, or
- now calls the restored helpers rather than depending on merge-regressed behavior.

- [ ] **Step 2: Adjust loop-runner/compatibility paths only where the checklist says `adapt`**

Examples include any call sites that currently assume:
- name derives from `account_id`
- invalid email create is allowed
- missing `model_mapping` is correct
- resume no longer normalizes parent state

Do not make unrelated structural changes.

- [ ] **Step 3: Run the compatibility-focused tests**

Run:

```bash
python -m unittest tools.codex_register.test_codex_register_service.LoopStateTests -v
python -m unittest tools.codex_register.test_codex_register_service.LoopRoundTests -v
python -m unittest tools.codex_register.test_codex_register_service.LoopMutualExclusionTests -v
python -m unittest tools.codex_register.test_codex_register_service.DataDirectoryContractTests -v
```

Expected: PASS

- [ ] **Step 4: Run the spec-mandated processing-flow gate**

Run exactly:

```bash
python -m unittest tools.codex_register.test_codex_register_service.ProcessingFlowTests -v
```

Expected: PASS

- [ ] **Step 5: Run the full suite for the file**

Run:

```bash
python -m unittest tools.codex_register.test_codex_register_service -v
```

Expected: PASS

- [ ] **Step 6: Perform the spec-required behavior-level verification outside the test runner**

Record concrete post-run checks in the worker-local checklist for:
- parsing behavior matches `5c211aca^1`
- upsert create/update matches `5c211aca^1`
- new-account naming matches `5c211aca^1`
- `model_mapping` matches `5c211aca^1`
- resume parent chain matches `5c211aca^1`

This can be done by citing the restored tests and the final code locations that now encode the baseline behavior.

- [ ] **Step 7: Perform the spec-required compatibility verification explicitly**

Record concrete evidence in the worker-local checklist that later-added capabilities still work without overriding baseline logic:
- loop runner interface/state behavior
- accounts list capability
- stats / offset / round-history behavior

Use the passing test groups to back each item:
- `LoopStateTests`
- `LoopRoundTests`
- `LoopMutualExclusionTests`
- `DataDirectoryContractTests`
- `ProcessingFlowTests`

- [ ] **Step 8: Verify the restoration checklist is fully resolved**

For each `5c211aca^1..5c211aca` hunk in the two target files, record final status in the worker-local checklist:
- restored to baseline
- intentionally kept
- adapted to call baseline

Expected: no unclassified hunks, no missing rationale lines, and no leftover regression semantics.

- [ ] **Step 9: Commit (only if explicitly requested by the user at execution time)**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
git commit -m "fix: restore pre-merge codex register logic"
```
