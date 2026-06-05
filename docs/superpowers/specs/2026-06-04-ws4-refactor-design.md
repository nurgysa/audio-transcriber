# WS-4 God-Object Decomposition — Design (adversarially reviewed)

**Date:** 2026-06-04
**Status:** Designed + adversarially reviewed; awaiting execution (deferred to a later session by the user)
**Source:** `design-ws4-refactor` workflow (7 agents: 3 analyze · 2 design A/B · judge · adversarial critic). Full output was in `%TEMP%/.../tasks/wlamuwykj.output` (ephemeral) — the actionable synthesis is captured here.

## Context

Two UI God-objects from the audit:
- `ui/dialogs/extract_tasks/__init__.py` — ~2095 LOC, ~72 methods.
- `ui/dialogs/settings.py` — ~1005 LOC, ~49 methods.

Goal: behavior-preserving decomposition on the GREEN test net (~691 tests), modeled on the proven `ui/app/` mixin+`builder.py` split. Extracted non-UI logic MUST be import-safe (no Tk/sounddevice at import) so it's unit-testable on the Linux CI (which can't import `ui.app`/`ui.dialogs` — sounddevice→PortAudio).

## Verdict: Qualified GO — 4 scoped PRs only

The adversarial critic CUT three items from the naive plan and caught a real regression. **Execute only these 4 low-risk PRs** (smallest-risk-first; squash-merge each before opening the next within a track; the two tracks are independent and may run in parallel):

### extract_tasks track
**PR-1 — `ui/dialogs/extract_tasks/pricing.py`** (unambiguously good, do first)
- Move `format_real_cost(usage, model) -> str` (from `_format_real_cost`, ~40 LOC of real branch logic) + `estimate_cost_hint(char_count) -> str` (from `_update_cost_hint`'s pure part).
- Move `_MODEL_PRICING_USD_PER_M` + `_COST_PER_1M_INPUT_TOKENS_USD` from `constants.py` → `pricing.py` (no back-compat shim needed — `test_extract_dialog_backend_dicts.py` only asserts `_NAME_TO_DISPLAY`/`_DISPLAY_TO_NAME`/`_CACHE_KEY_BY_BACKEND`/`_REQUIRED_KEYS_BY_BACKEND`, NOT the pricing constants — verified).
- Dialog: 2 method bodies → 1-liners. New `tests/test_extract_pricing.py` (~6 tests, cover the `<50` sentinel + the `*1.3` fudge). No Tk, no GUI smoke.

**PR-2 — `ui/dialogs/extract_tasks/cache_helpers.py`**
- Move ONLY `load_cached_containers(config, cache_key, ttl) -> list|None` (TTL freshness + dict→Container rebuild; `Container` imported INSIDE the function, per existing `__init__.py:735` pattern).
- SKIP `compute_enabled_backends` (14 lines, not worth a move). `update_recent_models` as a pure fn is OK IF included, but **apply its patch at the EXISTING worker-thread call site (`_run_extraction` ~line 1030), unconditionally — do NOT relocate it into `_on_extract_success`** (see CUT #1 below).
- Verify `test_dialog_dedup_ui.py:45` ordering still holds (`self._run_dedup(` before `self.after(0, self._on_extract_success` — position unchanged). ~4 tests for `load_cached_containers` (fresh/stale/corrupt-ts/empty).

### settings track
**PR-3 — `ui/dialogs/settings_helpers.py` (banner FSM)**
- `compute_banner_state(cloud_key, lang_label, provider_name, languages, providers) -> (action, text)` (verbatim decision tree from `_update_banner`, minus widget calls). Dialog keeps the `self._banner.configure/.grid/.grid_remove` + `_banner_action`. ~5 tests. 30-sec GUI smoke (type/clear key, toggle mixed+Deepgram).

**PR-4 — `ui/dialogs/settings_helpers.py` (formatters)**
- The four `format_{openrouter,linear,glide,trello}_success(info) -> str` (pure dict→string, real branch logic). ~4 tests, no smoke.

## CUT from WS-4 (adversarial critic's findings — DO NOT do these as part of WS-4)

1. **`_remember_recent_model` relocation = cancel-path REGRESSION (HIGH).** The naive plan moved the recent-model config write from the worker thread into `_on_extract_success` (main thread), calling it a "thread-safety fix, no behavior change." FALSE: today the write is **unconditional** before the cancel check; `_on_extract_success` does NOT fire on cancel. Relocating it means a user who cancels during the multi-second dedup/protocol window **silently loses their chosen model**. This is exactly the `feedback_relocating_code_audit_all_invariants` (#30→#31→#32) bug class. **Keep the write on the worker thread at its current call site.**

2. **`dedup_controller.py` extraction breaks 5 assertions across 2 test files (BLOCKER).** The plan named only `test_dialog_dedup_board_source.py`; it MISSED `test_dialog_dedup_ui.py` which whole-text-scans `DIALOG` for `resolve_thresholds`, `(OSError, LinearError, TrelloError, ValueError, KeyError)`, `select_match`, `supports_comments`, `dedup_enabled` — all `_run_dedup`-body-only strings. Moving the body reds 5 assertions. `_run_dedup` is 48 LOC, "low-value." **Drop it.**

3. **`gdrive/backup_worker.py` = 6-line passthrough (MEDIUM).** The orchestration already lives in `gdrive/backup.py::run_backup` (tested; its work_dir-leak was fixed in PR #111). What's left in the dialog is irreducible view glue (`mkdtemp` + thread + `self.after`). **Drop it.**

4. **The four `validate_*` extractions (MEDIUM).** Each is 4 lines; extraction yields only mock-verification tests ("we called validate_key + close"). **Drop them** — keep the formatters (real value).

## Honest limitation (don't oversell)

These 4 PRs extract the **import-safe, unit-testable leaf logic** — real, durable value (de-risks the Linux-CI-blind dialogs). But they do **NOT** meaningfully shrink the God-objects: post-refactor ≈ extract 1988 LOC (−5%), settings 875 LOC (−13%). The real mass — the 250-LOC `_build_ui`, 194-LOC `_run_extraction`, the five `_build_*_section` methods, the send/retry worker — is untouched.

## Deferred to a FOLLOW-ON WS (the one that actually shrinks the classes)

**Widget-tree-as-free-function extraction**, modeled exactly on `ui/app/builder.py`: `build_form(dialog)` / `build_ui(dialog)` for `extract_tasks`, and lifting the five `_build_*_section` methods in `settings`. This is where the LOC actually drops. Bigger, UI-risky, needs GUI smoke — its own WS.

## Conventions
- Commit msgs: `refactor(extract_tasks): extract pricing logic to pricing.py`, etc.
- Test cmd: `.venv-build/Scripts/python.exe -m pytest` (+ `-m ruff check .`) — that venv has pytest/pytest-asyncio/pytest-timeout/pytest-cov/mcp/ruff installed.
- Each PR: TDD (RED first), full suite green + ruff clean, behavior-preserving.
