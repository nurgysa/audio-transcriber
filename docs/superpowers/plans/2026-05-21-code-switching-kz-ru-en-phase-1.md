# Code-switching KZ+RU+EN Phase 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `"Смешанный (KZ+RU+EN)"` language option that propagates through the codebase as a `"mixed"` sentinel, enabling improved trilingual transcription on both local Whisper and 4 of 5 cloud providers.

**Architecture:** Single sentinel `"mixed"` flows from `LANGUAGES` dict → `TranscriptionOptions.language` → either local Whisper (`language=None` + trilingual `initial_prompt`) or cloud provider configs (each provider's native multilingual API). New `supports_mixed()` capability on the provider ABC declares per-provider compatibility. All changes additive; existing single-language paths physically unchanged.

**Tech Stack:** Python 3.10, faster-whisper, customtkinter (UI), pytest, ruff. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-05-21-code-switching-kz-ru-en-design.md` (commit 8f5f07d on `feat/code-switching-spec`).

---

## Pre-flight (do once before starting)

- [ ] Confirm spec is committed: `git log --oneline -1 docs/superpowers/specs/2026-05-21-code-switching-kz-ru-en-design.md` → should show commit `8f5f07d`.
- [ ] Confirm baseline tests green: `pytest -q` → should report `285 passed` (per CLAUDE.md baseline).
- [ ] Confirm ruff clean: `python -m ruff check .` → exit code 0.
- [ ] Ship spec PR first (current branch `feat/code-switching-spec`):
      ```
      git push -u origin feat/code-switching-spec
      gh pr create --title "docs: design spec for code-switching KZ+RU+EN (Phase 1)" --body "Per docs/superpowers/specs/2026-05-21-code-switching-kz-ru-en-design.md. Spec-only PR; implementation follows in PR-A through PR-D."
      ```
- [ ] Wait for spec PR to merge to `main` before starting PR-A (per [feedback_stacked_pr_squash_merge.md](C:\Users\nurgisa\.claude\projects\C--Users-nurgisa-Documents-audio-transcriber\memory\feedback_stacked_pr_squash_merge.md) — no stacking).

## File map

| PR | File | Change | Estimated LOC |
|---|---|---|---|
| A | `ui/app/constants.py` | +1 entry in `LANGUAGES` | 1 |
| A | `transcriber/prompt.py` | +1 entry in `_PROMPT_FRAMES` | 5 |
| A | `transcriber/__init__.py` | +1 translator line in `transcribe()` body | 3 |
| A | `providers/base.py` | +`supports_mixed()` default method + update `language` field comment | 7 |
| A | `tests/test_transcriber_pure.py` | +3 tests for `_build_initial_prompt("mixed", …)` | 25 |
| A | `tests/test_providers_base.py` (new) | +2 tests for ABC default | 20 |
| B | `providers/gladia.py` | branch in `_submit()` for `mixed` | 5 |
| B | `providers/deepgram.py` | override `supports_mixed()` + early-raise in `_submit()` | 8 |
| B | `tests/test_providers_gladia.py` | +2 tests (mixed body + single-lang regression) | 35 |
| B | `tests/test_providers_deepgram.py` | +2 tests (mixed raises + supports_mixed=False) | 25 |
| C | `providers/assemblyai.py` | branch in `_submit()` for `mixed` | 4 |
| C | `providers/speechmatics.py` | branch in `_submit()` for `mixed` | 4 |
| C | `providers/openai_whisper.py` | branch in `_submit()` for `mixed` | 3 |
| C | `tests/test_providers_assemblyai.py` | +1 test | 15 |
| C | `tests/test_providers_speechmatics.py` | +1 test | 15 |
| C | `tests/test_providers_openai_whisper.py` | +1 test | 15 |
| D | `ui/dialogs/settings.py` | +inline warning widget + show/hide logic | 30 |

**Total**: ~220 LOC across 4 PRs (close to spec's ~210 estimate).

## Branch strategy

One topic branch per PR. Each branch is created off `main` AFTER the previous PR has merged. No stacking.

```
main (after spec PR merge)
 ├── feat/code-switching-foundation       → PR-A
 │
 main (after PR-A merge)
 ├── feat/code-switching-cloud-known       → PR-B
 │
 main (after PR-B merge)
 ├── feat/code-switching-cloud-tbd         → PR-C
 │
 main (after PR-C merge)
 ├── feat/code-switching-ui-warning        → PR-D
```

---

## PR-A: Foundation

**Branch:** `feat/code-switching-foundation` (created from `main` after spec PR merges).

**Goal:** Lay all foundation pieces (sentinel, prompt frame, translator, ABC capability) so subsequent PRs can branch on `language == "mixed"` without coordination.

**Pre-task:**

```bash
git checkout main && git pull --ff-only origin main
git checkout -b feat/code-switching-foundation
```

---

### Task A.1: Add `"Смешанный (KZ+RU+EN)"` to `LANGUAGES`

**Files:**
- Modify: `ui/app/constants.py` (the `LANGUAGES` dict, currently lines 10-15)
- Test: `tests/test_ui_constants.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `tests/test_ui_constants.py`:

```python
"""Tests for ui/app/constants.py — small dict-level invariants.

Kept separate from UI tests because LANGUAGES, MODELS, SPEAKER_COUNTS etc.
are pure data structures imported by both UI and non-UI code paths
(Settings dialog + Transcriber's language hint plumbing).
"""
from __future__ import annotations

from ui.app.constants import LANGUAGES


def test_languages_contains_mixed_sentinel():
    """The `Смешанный (KZ+RU+EN)` entry must map to the `mixed` sentinel —
    the same string the rest of the codebase branches on
    (transcriber/__init__.py, transcriber/prompt.py, providers/*.py).
    """
    assert "Смешанный (KZ+RU+EN)" in LANGUAGES
    assert LANGUAGES["Смешанный (KZ+RU+EN)"] == "mixed"


def test_languages_preserves_single_lang_entries():
    """Regression: existing single-language entries unchanged."""
    assert LANGUAGES["Авто-определение"] is None
    assert LANGUAGES["Казахский"] == "kk"
    assert LANGUAGES["Русский"] == "ru"
    assert LANGUAGES["English"] == "en"
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_ui_constants.py -v
```
Expected: `test_languages_contains_mixed_sentinel` FAILS with `AssertionError: assert 'Смешанный (KZ+RU+EN)' in {...}`.

- [ ] **Step 3: Add the entry to `LANGUAGES`**

In `ui/app/constants.py`, edit the `LANGUAGES` dict to add the new entry after `English`:

```python
LANGUAGES = {
    "Авто-определение": None,
    "Казахский": "kk",
    "Русский": "ru",
    "English": "en",
    "Смешанный (KZ+RU+EN)": "mixed",
}
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_ui_constants.py -v
```
Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/app/constants.py tests/test_ui_constants.py
git commit -m "feat(ui/constants): add 'Смешанный (KZ+RU+EN)' language option

Sentinel value 'mixed' will be branched on in subsequent commits
(transcriber prompt frame, providers/* request bodies)."
```

---

### Task A.2: Add `"mixed"` frame to `_PROMPT_FRAMES`

**Files:**
- Modify: `transcriber/prompt.py` (the `_PROMPT_FRAMES` dict at lines 28-41)
- Test: `tests/test_transcriber_pure.py` (extend existing `_build_initial_prompt` block)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_transcriber_pure.py` after `test_initial_prompt_truncates_at_last_comma` (around line 56):

```python
# ── _build_initial_prompt with "mixed" sentinel ────────────────────


def test_initial_prompt_mixed_includes_trilingual_frame():
    """`mixed` produces a frame mentioning all three languages so Whisper's
    decode context biases toward accepting foreign-language inserts."""
    out = _build_initial_prompt(language="mixed", hotwords_str=None)
    assert out is not None
    assert "қазақша" in out
    assert "русский" in out
    assert "English" in out


def test_initial_prompt_mixed_with_terms_uses_trilingual_label():
    """When hotwords supplied with `mixed`, the terms label is itself
    trilingual ("Terms / Терминдер / Терминов")."""
    out = _build_initial_prompt(language="mixed", hotwords_str="Slack, Нургиса")
    assert out is not None
    assert "Slack" in out
    assert "Нургиса" in out
    # Trilingual terms label — any one of the three keywords proves
    # we picked the "mixed" frame, not "Terms:" fallback.
    assert ("Терминдер" in out) or ("Терминов" in out) or ("Terms" in out)


def test_initial_prompt_mixed_no_terms_omits_label():
    """Frame-only (no hotwords) must not emit a dangling terms label."""
    out = _build_initial_prompt(language="mixed", hotwords_str=None)
    assert out is not None
    assert "Терминдер" not in out
    assert "Терминов" not in out
    assert "Terms" not in out
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_transcriber_pure.py -v -k mixed
```
Expected: all 3 tests FAIL — `_PROMPT_FRAMES.get("mixed")` currently returns None, so `_build_initial_prompt` returns None (or "Terms: …" without the frame).

- [ ] **Step 3: Add the `"mixed"` frame**

In `transcriber/prompt.py`, edit the `_PROMPT_FRAMES` dict to add a fourth entry after `"en"`:

```python
_PROMPT_FRAMES: dict[str, dict[str, str]] = {
    "ru": {
        "prefix": "Расшифровка разговора на русском языке.",
        "terms_label": "Упомянутые термины",
    },
    "kk": {
        "prefix": "Қазақ тіліндегі әңгіменің жазбасы.",
        "terms_label": "Аталған терминдер",
    },
    "en": {
        "prefix": "Transcript of a spoken conversation in English.",
        "terms_label": "Terms mentioned",
    },
    "mixed": {
        "prefix": (
            "Расшифровка трилингвальной (қазақша, русский, English) речи. "
            "Слова и термины могут переключаться между языками."
        ),
        "terms_label": "Терминдер / Терминов / Terms",
    },
}
```

- [ ] **Step 4: Run all `_build_initial_prompt` tests**

```
pytest tests/test_transcriber_pure.py -v -k initial_prompt
```
Expected: all original tests + 3 new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add transcriber/prompt.py tests/test_transcriber_pure.py
git commit -m "feat(transcriber/prompt): trilingual frame for 'mixed' language

initial_prompt is decode-context for Whisper; a trilingual prefix
('Расшифровка трилингвальной...') biases acceptance of foreign-language
tokens. Hotwords still bias via CTC scoring (complementary mechanism)."
```

---

### Task A.3: Add `effective_language` translator in `transcribe()`

**Files:**
- Modify: `transcriber/__init__.py` (the `transcribe()` method body around line 624-630, just before `_build_initial_prompt` is called)
- Test: covered by integration; we add a pure-helper extraction so it's directly testable

This task extracts a tiny helper `_effective_whisper_language(language)` next to `_build_initial_prompt` so it can be unit-tested without spinning up Whisper. The helper does the one-line translation and is called at both the local Whisper code path AND inside `_build_initial_prompt`'s call site.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_transcriber_pure.py` (after the new mixed tests), and update the import line at the top of the file to add `_effective_whisper_language`:

```python
# At top of file, update the import block:
from transcriber import (
    TranscriptionCancelled,
    _assign_speakers_word_level,
    _build_initial_prompt,
    _check_cancelled,
    _effective_whisper_language,  # NEW
    _find_speaker_by_overlap,
    _parse_progress_line,
    _speaker_at_time,
)

# Then add the test block (after the mixed tests):

# ── _effective_whisper_language ────────────────────────────────────


def test_effective_lang_mixed_becomes_none():
    """Whisper API expects None for auto-detect; "mixed" is our internal
    sentinel that means "let Whisper auto-detect but build a trilingual
    initial_prompt"."""
    assert _effective_whisper_language("mixed") is None


def test_effective_lang_passes_through_single_codes():
    """Single-language codes are passed through verbatim."""
    assert _effective_whisper_language("ru") == "ru"
    assert _effective_whisper_language("kk") == "kk"
    assert _effective_whisper_language("en") == "en"


def test_effective_lang_none_stays_none():
    """None (UI's "Авто-определение") stays None."""
    assert _effective_whisper_language(None) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_transcriber_pure.py -v -k effective_lang
```
Expected: tests FAIL with `ImportError: cannot import name '_effective_whisper_language' from 'transcriber'`.

- [ ] **Step 3: Add the helper and use it in `transcribe()`**

In `transcriber/prompt.py`, add the helper at the bottom of the file (it's a "pure helper" sibling of `_build_initial_prompt`, so it lives here):

```python
def _effective_whisper_language(language: str | None) -> str | None:
    """Translate UI-level sentinel to the value faster-whisper expects.

    The codebase uses the string ``"mixed"`` to mark «multilingual KZ+RU+EN
    decoding» — that's a sentinel for OUR layer (it drives prompt-frame
    selection in `_build_initial_prompt`). Faster-whisper's
    `model.transcribe(language=...)` understands only:
      - a real ISO code ("ru", "kk", "en", …), or
      - None (= auto-detect dominant language across the file).
    So for "mixed", we pass None to Whisper, while `_build_initial_prompt`
    keeps the "mixed" key for its dict-lookup.
    """
    if language == "mixed":
        return None
    return language
```

In `transcriber/__init__.py`, re-export the new helper so it's importable from the package:

```python
# Near the existing imports in transcriber/__init__.py (around line 30-60),
# locate where _build_initial_prompt is imported and add _effective_whisper_language:

from .prompt import _build_initial_prompt, _effective_whisper_language
```

Also at the top of `transcriber/__init__.py`, find the `__all__` (if it exists; PR #18 added one) and add `"_effective_whisper_language"`:

```python
__all__ = [
    # … existing entries …
    "_effective_whisper_language",
]
```

Now use the helper at the Whisper call site. In `transcriber/__init__.py`, locate the `transcribe()` method around line 624. Add the translator line right before `_build_initial_prompt` is called, and update the Whisper invocation to use `effective_language`:

```python
# Around line 624 (just before existing hotwords_str line):
hotwords_str = hotwords.strip() if hotwords and hotwords.strip() else None

# NEW: translate the sentinel for the Whisper API while keeping the
# original `language` for prompt-frame lookup.
effective_language = _effective_whisper_language(language)

initial_prompt = _build_initial_prompt(language, hotwords_str)
```

Then locate the call `model.transcribe(...)` further down in the same method (was at line ~747 per earlier grep), and replace `language=language` with `language=effective_language`:

```python
segments, _info = model.transcribe(
    audio_path,
    language=effective_language,   # was: language=language
    initial_prompt=initial_prompt,
    hotwords=hotwords_list,
    # … other args unchanged …
)
```

- [ ] **Step 4: Run all transcriber pure tests + smoke-run full suite**

```
pytest tests/test_transcriber_pure.py -v
pytest -q
```
Expected: all tests PASS, including the 3 new `effective_lang` ones. Full suite stays at 285+ green.

- [ ] **Step 5: Commit**

```bash
git add transcriber/prompt.py transcriber/__init__.py tests/test_transcriber_pure.py
git commit -m "feat(transcriber): translate 'mixed' sentinel to None for Whisper

New _effective_whisper_language() helper sits next to _build_initial_prompt
in transcriber/prompt.py. It maps our UI-level 'mixed' sentinel to None for
the Whisper API while leaving 'mixed' intact for the prompt-frame lookup.
Single-language codes pass through unchanged."
```

---

### Task A.4: Add `supports_mixed()` default on `TranscriptionProvider` ABC

**Files:**
- Modify: `providers/base.py` (the `TranscriptionProvider` class at lines 60+; also the `TranscriptionOptions.language` field comment at line 28)
- Test: `tests/test_providers_base.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `tests/test_providers_base.py`:

```python
"""Tests for providers.base — ABC defaults and TranscriptionOptions contract."""
from __future__ import annotations

from providers.base import (
    TranscriptionOptions,
    TranscriptionProvider,
    TranscriptionResult,
)


class _StubProvider(TranscriptionProvider):
    """Minimal subclass that only implements the abstract transcribe(),
    so we can probe inherited behavior like supports_mixed()."""

    display_name = "Stub"
    supports_diarization = False

    def transcribe(self, audio_path, options, on_status=None, on_progress=None, cancel_event=None):
        return TranscriptionResult(segments=[])


def test_supports_mixed_default_true():
    """ABC default: providers opt in to 'mixed' unless they explicitly
    declare otherwise. The 4 of 5 providers that support KZ/RU/EN ride
    the default; Deepgram overrides to False (lacks KZ in nova-3)."""
    p = _StubProvider()
    assert p.supports_mixed() is True


def test_transcription_options_accepts_mixed_language():
    """The dataclass shouldn't reject the new sentinel string —
    .language is typed `str | None` with no validator."""
    opts = TranscriptionOptions(language="mixed")
    assert opts.language == "mixed"
```

- [ ] **Step 2: Run test to verify the first one fails**

```
pytest tests/test_providers_base.py -v
```
Expected: `test_supports_mixed_default_true` FAILS with `AttributeError: '_StubProvider' object has no attribute 'supports_mixed'`. The second test (`test_transcription_options_accepts_mixed_language`) should already pass since the dataclass has no validator.

- [ ] **Step 3: Add `supports_mixed()` to the ABC and update the language comment**

In `providers/base.py`:

1. Update the `TranscriptionOptions.language` field comment (around line 28):

```python
@dataclass
class TranscriptionOptions:
    """Per-call options. Providers map these to their native API params."""

    language: str | None = None        # "ru" | "kk" | "en" | "mixed" | None=auto
    # "mixed" is the KZ+RU+EN code-switching sentinel; providers branch on
    # it in _submit() and enable their native multilingual mode. Providers
    # that can't handle one of KZ/RU/EN declare supports_mixed() -> False
    # and raise ProviderError when called with language="mixed".
    diarize: bool = False
    # … rest unchanged …
```

2. Add the `supports_mixed()` method to `TranscriptionProvider` (after `supports_diarization`, before `transcribe`):

```python
class TranscriptionProvider(ABC):
    """Cloud transcription backend interface.

    Subclasses are expected to be cheap to construct — keep heavy state
    (HTTP sessions, etc.) lazy. Each ``transcribe()`` call is a single
    job; the provider must honour ``cancel_event`` between long
    operations (uploads, polls).
    """

    #: Human-readable name shown in the Settings dropdown.
    display_name: str = ""

    #: True when the provider returns speaker labels (so the
    #: "Диаризация" checkbox is meaningful in cloud mode).
    supports_diarization: bool = False

    def supports_mixed(self) -> bool:
        """Whether this provider supports the KZ+RU+EN code-switching mode.

        Default True — all currently-supported providers EXCEPT Deepgram
        ship KZ in their multilingual models. Deepgram's nova-3 omits KZ
        and overrides this to False, then raises ProviderError when called
        with `options.language == "mixed"`.

        Used by Settings UI to surface an inline warning when the current
        provider can't service a stored 'Смешанный (KZ+RU+EN)' language
        preference, and by the test suite to verify the capability
        contract.
        """
        return True

    @abstractmethod
    def transcribe(
        # … unchanged …
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_providers_base.py -v
pytest -q
```
Expected: both new tests PASS. Full suite stays green (the existing 285 + new tests).

- [ ] **Step 5: Commit**

```bash
git add providers/base.py tests/test_providers_base.py
git commit -m "feat(providers/base): add supports_mixed() capability + 'mixed' option

New supports_mixed() method on the TranscriptionProvider ABC declares
whether the provider can handle the KZ+RU+EN code-switching sentinel.
Default True; Deepgram will override to False in PR-B because nova-3
lacks Kazakh. TranscriptionOptions.language docstring updated to list
'mixed' alongside the ISO codes."
```

---

### PR-A wrap-up

- [ ] **Run full suite + lint**

```
pytest -q
python -m ruff check .
```
Expected: all tests pass (baseline 285 + new tests from A.1-A.4 = ~293); ruff exits 0.

- [ ] **Push and open PR**

```bash
git push -u origin feat/code-switching-foundation
gh pr create --title "feat(code-switching): foundation (sentinel + ABC capability) [PR-A]" --body "$(cat <<'EOF'
## Summary

Foundation for the KZ+RU+EN code-switching feature (Phase 1, PR-A of 4).

- `LANGUAGES["Смешанный (KZ+RU+EN)"] = "mixed"` sentinel
- `_PROMPT_FRAMES["mixed"]` — trilingual prompt frame for Whisper
- `_effective_whisper_language()` — translates `"mixed"` → `None` for Whisper API
- `TranscriptionProvider.supports_mixed()` ABC method, default `True`
- New tests covering all four pieces

All changes additive: existing single-language paths (`kk`/`ru`/`en`/`None`) are physically unchanged.

Subsequent PRs (B/C/D) wire up cloud providers and the Settings UI. See
[spec](docs/superpowers/specs/2026-05-21-code-switching-kz-ru-en-design.md)
for the full design.

## Test plan

- [x] `pytest -q` — all 285 baseline + ~8 new tests green
- [x] `python -m ruff check .` — clean
- [x] Manual sanity: open the app, confirm `Смешанный (KZ+RU+EN)` appears in the language dropdown and can be selected without errors (no transcribe yet — that's PR-B/C/D)
EOF
)"
```

- [ ] **Wait for review + merge before starting PR-B.** Per memory note about squash-merge orphaning stacked PRs.

---

## PR-B: Cloud — Gladia + Deepgram

**Branch:** `feat/code-switching-cloud-known` (created from `main` after PR-A merges).

**Goal:** Wire mixed-mode into the two providers with known/documented API surface: Gladia (explicit `code_switching` flag) and Deepgram (hard reject because nova-3 lacks KZ).

**Pre-task:**

```bash
git checkout main && git pull --ff-only origin main
git checkout -b feat/code-switching-cloud-known
```

---

### Task B.1: Gladia mixed-mode

**Files:**
- Modify: `providers/gladia.py` (the `_submit()` method around lines 150-170 where the body dict is built)
- Test: `tests/test_providers_gladia.py` (add new tests after the existing `_to_segments` block)

- [ ] **Step 1: Research Gladia code_switching payload shape**

Visit Gladia API docs and confirm the exact payload format before writing the test:

- Primary: https://docs.gladia.io/api-reference/v2/pre-recorded/post
- Search the docs for: `code_switching`, `language_config`, `languages`

Confirm these answers and record below (replace `___` with actual findings if different):

- Is `code_switching` a top-level body field or nested inside `language_config`? **Likely nested**: `body["language_config"] = {"languages": [...], "code_switching": true}`
- What's the languages list format? **Likely** an array of ISO 639-1 codes: `["kk", "ru", "en"]`
- Does Gladia accept `"kk"` as the Kazakh code? Check the language matrix in the docs.

**If docs disagree with the above, update the test code in Step 2 to match what docs say.** This step is the gate — don't proceed to Step 2 until the payload shape is confirmed.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_providers_gladia.py`:

```python
# ── language="mixed" branch ───────────────────────────────────────────


def test_submit_mixed_enables_code_switching(fake_audio):
    """When options.language == 'mixed', the submit body must request
    code-switching across KZ+RU+EN. This is the Gladia equivalent of the
    'Смешанный' UI option."""
    p = GladiaProvider("test-key")

    submitted_body = {}

    def capture_post(url, headers=None, json=None, timeout=None, **kw):
        submitted_body.update(json or {})
        resp = MagicMock()
        resp.ok = True
        resp.status_code = 200
        resp.json = lambda: {"result_url": "https://example/r/1"}
        return resp

    with patch.object(p, "_upload", return_value="https://example/audio.wav"), \
         patch("providers.gladia.requests.post", side_effect=capture_post), \
         patch.object(p, "_poll", return_value={"result": {"transcription": {"utterances": []}}}):
        opts = TranscriptionOptions(language="mixed", diarize=False)
        p.transcribe(fake_audio, opts)

    assert submitted_body["language_config"] == {
        "languages": ["kk", "ru", "en"],
        "code_switching": True,
    }


def test_submit_single_language_unchanged(fake_audio):
    """Regression: language='ru' must produce the SAME body as before
    (no code_switching key, no languages list — just single forced language)."""
    p = GladiaProvider("test-key")

    submitted_body = {}

    def capture_post(url, headers=None, json=None, timeout=None, **kw):
        submitted_body.update(json or {})
        resp = MagicMock()
        resp.ok = True
        resp.status_code = 200
        resp.json = lambda: {"result_url": "https://example/r/1"}
        return resp

    with patch.object(p, "_upload", return_value="https://example/audio.wav"), \
         patch("providers.gladia.requests.post", side_effect=capture_post), \
         patch.object(p, "_poll", return_value={"result": {"transcription": {"utterances": []}}}):
        opts = TranscriptionOptions(language="ru", diarize=False)
        p.transcribe(fake_audio, opts)

    assert submitted_body["language_config"] == {"languages": ["ru"]}
    # code_switching key must NOT appear in single-language mode
    assert "code_switching" not in submitted_body.get("language_config", {})
```

- [ ] **Step 3: Run tests to verify they fail**

```
pytest tests/test_providers_gladia.py -v -k "mixed or single_language_unchanged"
```
Expected: `test_submit_mixed_enables_code_switching` FAILS because the current code only passes `{"languages": ["mixed"]}` (treating mixed as a forced language, which Gladia would reject anyway). Regression test may already pass.

- [ ] **Step 4: Implement the `mixed` branch in `_submit()`**

In `providers/gladia.py`, locate `_submit()` (around line 150). The current single-language branch:

```python
if options.language:
    # Single forced language; code_switching defaults to False.
    body["language_config"] = {"languages": [options.language]}
```

Replace it with:

```python
if options.language == "mixed":
    # KZ+RU+EN code-switching mode. Gladia's `code_switching` flag
    # enables true per-segment language switching across the listed
    # languages; without it, Gladia forces a single dominant language.
    body["language_config"] = {
        "languages": ["kk", "ru", "en"],
        "code_switching": True,
    }
elif options.language:
    # Single forced language (kk/ru/en); code_switching stays False.
    body["language_config"] = {"languages": [options.language]}
```

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/test_providers_gladia.py -v
pytest -q
```
Expected: both new tests PASS, all existing Gladia tests stay green, full suite stays green.

- [ ] **Step 6: Commit**

```bash
git add providers/gladia.py tests/test_providers_gladia.py
git commit -m "feat(providers/gladia): enable code_switching for 'mixed' option

When TranscriptionOptions.language=='mixed', submit
language_config={'languages':['kk','ru','en'], 'code_switching':true}.
Single-language paths (ru/kk/en) unchanged — explicit regression test
guards against accidental drift."
```

---

### Task B.2: Deepgram blocks mixed-mode

**Files:**
- Modify: `providers/deepgram.py` (override `supports_mixed()` + raise in `_submit()` around lines 170-180)
- Test: `tests/test_providers_deepgram.py` (add new tests after the existing block)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_providers_deepgram.py`:

```python
# ── supports_mixed = False + early-raise ──────────────────────────────


def test_supports_mixed_returns_false():
    """Deepgram nova-3 doesn't include Kazakh; reflect that as a
    capability the UI can read."""
    p = DeepgramProvider("test-key")
    assert p.supports_mixed() is False


def test_submit_mixed_raises_provider_error_before_http(fake_audio):
    """When called with language='mixed', Deepgram must raise BEFORE
    making any HTTP request — the rejection is at the contract layer,
    not after a server round-trip."""
    p = DeepgramProvider("test-key")

    with patch("providers.deepgram.requests.post") as mock_post:
        opts = TranscriptionOptions(language="mixed", diarize=False)
        with pytest.raises(ProviderError, match="Қазақша"):
            p.transcribe(fake_audio, opts)
        # The whole point of supports_mixed=False is to fail fast.
        assert mock_post.call_count == 0
```

Make sure the file's imports include `DeepgramProvider`, `pytest`, `patch`, `ProviderError`, `TranscriptionOptions` — match the existing pattern from the file's top. If the file doesn't yet import `pytest`, add it.

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_providers_deepgram.py -v -k "supports_mixed or mixed_raises"
```
Expected: both FAIL (`AttributeError` for the first since `supports_mixed` isn't overridden; the second fails because `_submit` currently issues the HTTP call with `language="mixed"`, which Deepgram rejects with a 400 but only AFTER the network round-trip).

- [ ] **Step 3: Implement override + early-raise**

In `providers/deepgram.py`, add `supports_mixed()` to the class (near `display_name` / `supports_diarization` declarations, around the top of the `DeepgramProvider` class body):

```python
class DeepgramProvider(TranscriptionProvider):
    display_name = "Deepgram"
    supports_diarization = True  # if not already there

    def supports_mixed(self) -> bool:
        # nova-3 multilingual covers ~30 languages but not Kazakh.
        # See https://developers.deepgram.com/docs/models-languages-overview
        return False
```

Then in `_submit()` (around line 170 where the language is read), add an early guard at the top of the method (before any HTTP work):

```python
def _submit(self, audio_path: str, options: TranscriptionOptions, on_progress) -> dict:
    if options.language == "mixed":
        raise ProviderError(
            "Deepgram nova-3 не поддерживает Қазақша. "
            "Для трилингвальной транскрипции выбери Gladia или AssemblyAI."
        )
    # … rest of method unchanged …
```

The exact placement: locate the method signature for `_submit` (or whichever method does the HTTP POST — Deepgram has a single-call flow). Add the guard as the first statement inside the body, before the `params` list is built.

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_providers_deepgram.py -v
pytest -q
```
Expected: both new tests PASS, existing Deepgram tests stay green.

- [ ] **Step 5: Commit**

```bash
git add providers/deepgram.py tests/test_providers_deepgram.py
git commit -m "feat(providers/deepgram): block 'mixed' (nova-3 lacks KZ)

supports_mixed() returns False — surfaces the limitation to the
Settings UI (PR-D) — and _submit() raises ProviderError BEFORE any
HTTP call when language=='mixed', so users with Deepgram selected get
a clear Russian-language message ('Deepgram nova-3 не поддерживает
Қазақша...') instead of a generic 400 from the server."
```

---

### PR-B wrap-up

- [ ] **Run full suite + lint**

```
pytest -q
python -m ruff check .
```
Expected: all tests pass; ruff clean.

- [ ] **Push and open PR**

```bash
git push -u origin feat/code-switching-cloud-known
gh pr create --title "feat(code-switching): Gladia + Deepgram cloud paths [PR-B]" --body "$(cat <<'EOF'
## Summary

Cloud-path wiring for `language=='mixed'` on the two providers whose APIs are explicitly known:

- **Gladia**: enable `code_switching: true` with `languages: ['kk','ru','en']` in `language_config`. The flag was already mentioned in our existing code comment (`providers/gladia.py:157` — "defaults to False") but never enabled.
- **Deepgram**: override `supports_mixed()` to False (nova-3 lacks KZ) and raise `ProviderError` early in `_submit()` with a Russian-language message pointing the user at Gladia / AssemblyAI.

Builds on PR-A foundation. Subsequent PR-C adds AssemblyAI/Speechmatics/OpenAI Whisper after doc verification of their multilingual APIs.

## Test plan

- [x] `pytest -q` — all green including +4 new tests
- [x] `python -m ruff check .` — clean
- [x] Manual: with a Gladia key and a short trilingual audio clip, run `Смешанный` mode end-to-end (single dogfood test, just to confirm the request shape doesn't crash)
- [x] Manual: with Deepgram selected and `Смешанный`, click Транскрибировать — confirm the Russian error message appears in a dialog with no network round-trip
EOF
)"
```

- [ ] **Wait for review + merge before starting PR-C.**

---

## PR-C: Cloud — AssemblyAI + Speechmatics + OpenAI Whisper

**Branch:** `feat/code-switching-cloud-tbd` (created from `main` after PR-B merges).

**Goal:** Wire mixed-mode into the three providers whose multilingual API specifics need confirmation against current vendor docs. Each task starts with a research step.

**Pre-task:**

```bash
git checkout main && git pull --ff-only origin main
git checkout -b feat/code-switching-cloud-tbd
```

---

### Task C.1: AssemblyAI mixed-mode

**Files:**
- Modify: `providers/assemblyai.py` (the `_submit()` method around lines 175-195 where the body dict is built)
- Test: `tests/test_providers_assemblyai.py`

- [ ] **Step 1: Research AssemblyAI multilingual API**

Visit AssemblyAI docs and confirm:

- Primary: https://www.assemblyai.com/docs/api-reference/transcripts/submit
- Also useful: https://www.assemblyai.com/docs/speech-to-text/speech-recognition (model overview)

Search the docs for:
- `language_detection` — already used in current code; confirm it stays correct for code-switching
- `speech_model` — values like `"universal"`, `"best"`, etc.
- `language_confidence_threshold` — optional knob for auto-detect

Confirm and record:

- To enable multilingual / code-switching: **likely** `body["language_detection"] = True` + `body["speech_model"] = "universal"` (the multilingual model)
- Does `language_detection: true` work per-segment, or only top-of-file? Check the docs.
- Is `"universal"` the correct value for `speech_model`, or has it been renamed (e.g. `"universal-2"`)?
- Is there a `multilingual: true` flag separate from `language_detection`? (Some APIs distinguish.)

**Record findings as code comments in Step 4's implementation.** If the API differs from "language_detection=true + speech_model=universal", update Step 2's assertions accordingly.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_providers_assemblyai.py`:

```python
# ── language="mixed" branch ───────────────────────────────────────────


def test_submit_mixed_enables_multilingual_universal_model(fake_audio):
    """language='mixed' must request AssemblyAI's multilingual ASR.
    Based on docs (verify URL in PR description), this means enabling
    language_detection AND switching to the 'universal' speech model
    (or whatever the current multilingual model is named)."""
    p = AssemblyAIProvider("test-key")

    submitted_body = {}

    def capture_post(url, headers=None, json=None, timeout=None, **kw):
        if "transcript" in url and "upload" not in url:
            submitted_body.update(json or {})
        resp = MagicMock()
        resp.ok = True
        resp.status_code = 200
        resp.json = lambda: {"id": "tid", "upload_url": "u"}
        return resp

    with patch("providers.assemblyai.requests.post", side_effect=capture_post), \
         patch.object(p, "_upload", return_value="https://example/audio.wav"), \
         patch.object(p, "_poll", return_value={"status": "completed", "text": "", "utterances": []}):
        opts = TranscriptionOptions(language="mixed", diarize=False)
        p.transcribe(fake_audio, opts)

    assert submitted_body.get("language_detection") is True
    assert submitted_body.get("speech_model") == "universal"
    # Hard-coded language_code must NOT appear in mixed mode
    assert "language_code" not in submitted_body
```

- [ ] **Step 3: Run test to verify it fails**

```
pytest tests/test_providers_assemblyai.py -v -k mixed
```
Expected: FAIL — current code sets `language_detection: True` for `None` but doesn't set `speech_model: "universal"`.

- [ ] **Step 4: Implement the `mixed` branch in `_submit()`**

In `providers/assemblyai.py`, locate the existing language block in `_submit()` (around line 179-183):

```python
# Language: explicit if supplied, else turn on auto-detection.
if options.language:
    body["language_code"] = options.language
else:
    body["language_detection"] = True
```

Replace with:

```python
# Language handling:
#   - "mixed" sentinel → multilingual ASR: enable language_detection and
#     switch to the 'universal' multilingual model (per AssemblyAI docs,
#     verified <YYYY-MM-DD>: <URL from Step 1>).
#   - Specific code (kk/ru/en) → force that language.
#   - None → auto-detect a single dominant language.
if options.language == "mixed":
    body["language_detection"] = True
    body["speech_model"] = "universal"
elif options.language:
    body["language_code"] = options.language
else:
    body["language_detection"] = True
```

- [ ] **Step 5: Run test to verify it passes**

```
pytest tests/test_providers_assemblyai.py -v
pytest -q
```
Expected: PASS, full suite green.

- [ ] **Step 6: Commit**

```bash
git add providers/assemblyai.py tests/test_providers_assemblyai.py
git commit -m "feat(providers/assemblyai): mixed-mode uses universal model

language='mixed' enables language_detection AND switches speech_model
to 'universal' (AssemblyAI's multilingual model). Verified against
docs/<date>: <docs URL>."
```

(Replace `<date>` and `<docs URL>` in the commit message with what you confirmed in Step 1.)

---

### Task C.2: Speechmatics mixed-mode

**Files:**
- Modify: `providers/speechmatics.py` (the `_build_config()` or `_submit()` method — find where the JSON config is assembled, around the `language` line at line 264 per earlier grep)
- Test: `tests/test_providers_speechmatics.py`

- [ ] **Step 1: Research Speechmatics language identification API**

Visit Speechmatics docs and confirm:

- Primary: https://docs.speechmatics.com/features/language-identification
- API reference: https://docs.speechmatics.com/jobsapi (look at the JSON config schema)

Search for:
- `language_identification_config`
- `expected_languages`
- How to enable multi-language on a job

Confirm and record:

- Field name (could be `language_identification`, `language_id_config`, etc.): **likely** `language_identification_config`
- Where it sits in the config (top-level vs nested in `transcription_config`)
- What values to pass for "expect KZ+RU+EN code-switching"
- Note: Speechmatics may use `"language": "auto"` to opt INTO auto-detection rather than passing an explicit code

**If the API differs from `language_identification_config: {"expected_languages": [...]}`, update Step 2's test.**

- [ ] **Step 2: Write the failing test**

Append to `tests/test_providers_speechmatics.py`:

```python
# ── language="mixed" branch ───────────────────────────────────────────


def test_submit_mixed_enables_language_identification(fake_audio):
    """language='mixed' must enable Speechmatics' language identification
    with KZ/RU/EN as expected candidates."""
    p = SpeechmaticsProvider("test-key")

    submitted_config = {}

    def capture_post(url, headers=None, data=None, files=None, timeout=None, **kw):
        # config is sent as a multipart field; pull it out
        if data and "config" in data:
            import json as _json
            submitted_config.update(_json.loads(data["config"]))
        resp = MagicMock()
        resp.ok = True
        resp.status_code = 201
        resp.json = lambda: {"id": "jid"}
        return resp

    with patch("providers.speechmatics.requests.post", side_effect=capture_post), \
         patch.object(p, "_poll", return_value={"job": {"status": "done"}}), \
         patch.object(p, "_fetch_transcript", return_value={"results": []}):
        opts = TranscriptionOptions(language="mixed", diarize=False)
        p.transcribe(fake_audio, opts)

    tc = submitted_config.get("transcription_config", submitted_config)
    # Either of these is acceptable depending on what the docs say —
    # update the assertion to match the confirmed field name.
    assert (
        tc.get("language") == "auto"
        or "language_identification_config" in tc
        or "language_identification" in tc
    ), f"Unexpected Speechmatics config for mixed: {submitted_config}"
```

The looser assertion is intentional — the test surfaces ANY of the valid Speechmatics multilingual paths. The implementation MUST match exactly one of them; the test simply verifies the implementation didn't fall through to the single-language branch.

- [ ] **Step 3: Run test to verify it fails**

```
pytest tests/test_providers_speechmatics.py -v -k mixed
```
Expected: FAIL — current code likely passes `language: "mixed"` directly which fails the assertion.

- [ ] **Step 4: Implement the `mixed` branch**

In `providers/speechmatics.py`, locate the config-building code. The current line (per earlier grep, line 264):

```python
"language": options.language or "auto",
```

This already accepts `"auto"` as a fallback. The simplest implementation: when `options.language == "mixed"`, pass `"auto"` to Speechmatics (which enables their built-in language ID) AND add `language_identification_config` if the API supports it for narrowing the candidate set.

Based on what you confirmed in Step 1, modify the config builder so the `mixed` path sets:

```python
if options.language == "mixed":
    transcription_config["language"] = "auto"
    transcription_config["language_identification_config"] = {
        "expected_languages": ["kk", "ru", "en"]
    }
else:
    transcription_config["language"] = options.language or "auto"
```

(The exact statements depend on how the existing code is structured — locate the dict literal where `"language"` is set and adapt accordingly.)

- [ ] **Step 5: Run test to verify it passes**

```
pytest tests/test_providers_speechmatics.py -v
pytest -q
```
Expected: PASS, full suite green.

- [ ] **Step 6: Commit**

```bash
git add providers/speechmatics.py tests/test_providers_speechmatics.py
git commit -m "feat(providers/speechmatics): mixed-mode enables language ID

language='mixed' switches Speechmatics into 'auto' language mode
with KZ/RU/EN in the expected_languages list. Verified against
docs/<date>: <docs URL>."
```

(Replace `<date>` and `<docs URL>` with what you confirmed.)

---

### Task C.3: OpenAI Whisper mixed-mode

**Files:**
- Modify: `providers/openai_whisper.py` (the multipart form assembly around lines 88-92 where `language` is conditionally added)
- Test: `tests/test_providers_openai_whisper.py`

- [ ] **Step 1: Research OpenAI Whisper code-switching**

Visit OpenAI API docs:

- Primary: https://platform.openai.com/docs/api-reference/audio/createTranscription

Confirm:

- What happens when `language` form field is omitted? (Expected: server auto-detects a single dominant language; no per-segment code-switching, just best-effort whole-file detection.)
- Is there a multilingual flag (e.g. `multilingual: true`)? Almost certainly NOT — `whisper-1` is hosted Whisper, single-language decode.
- Does `language: ""` differ from omitting the field?

Confirm: omitting the `language` field IS the documented way to opt into auto-detect. There's no native code-switching support for `whisper-1`; this is best-effort and the user should be informed.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_providers_openai_whisper.py`:

```python
# ── language="mixed" branch ───────────────────────────────────────────


def test_submit_mixed_omits_language_field(fake_audio):
    """`whisper-1` has no native code-switching mode. When language='mixed',
    we omit the language form field so OpenAI's server falls back to
    auto-detect — best-effort, but better than forcing a single language."""
    p = OpenAIWhisperProvider("test-key")

    sent_form_keys = set()

    def capture_post(url, headers=None, files=None, data=None, timeout=None, **kw):
        # OpenAI uses requests' `data=[(k,v), ...]` for the form;
        # collect the keys actually transmitted.
        if data is not None:
            for k, _v in (data if isinstance(data, list) else data.items()):
                sent_form_keys.add(k)
        resp = MagicMock()
        resp.ok = True
        resp.status_code = 200
        resp.json = lambda: {"text": "", "language": "ru", "segments": []}
        return resp

    with patch("providers.openai_whisper.requests.post", side_effect=capture_post):
        opts = TranscriptionOptions(language="mixed", diarize=False)
        p.transcribe(fake_audio, opts)

    # Critical: language must NOT be in the form when mixed
    assert "language" not in sent_form_keys
```

- [ ] **Step 3: Run test to verify it fails**

```
pytest tests/test_providers_openai_whisper.py -v -k mixed
```
Expected: FAIL — current code would send `data.append(("language", "mixed"))` which OpenAI's API would reject.

- [ ] **Step 4: Implement the `mixed` branch**

In `providers/openai_whisper.py`, locate the language block in `_submit()` (around line 88-92):

```python
if options.language:
    data.append(("language", options.language))
```

Replace with:

```python
# Whisper-1 has no native code-switching; the closest equivalent is
# to omit the language form field so the server's own detection
# kicks in. Best-effort only — for true multi-language audio,
# Gladia or AssemblyAI give qualitatively better results.
if options.language and options.language != "mixed":
    data.append(("language", options.language))
```

- [ ] **Step 5: Run test to verify it passes**

```
pytest tests/test_providers_openai_whisper.py -v
pytest -q
```
Expected: PASS, full suite green.

- [ ] **Step 6: Commit**

```bash
git add providers/openai_whisper.py tests/test_providers_openai_whisper.py
git commit -m "feat(providers/openai_whisper): mixed-mode omits language field

whisper-1 has no native code-switching; omitting the language form
field falls back to OpenAI's server-side single-language detection
('best-effort' for trilingual audio). Inline comment notes that
Gladia / AssemblyAI are qualitatively better for true multi-language."
```

---

### PR-C wrap-up

- [ ] **Run full suite + lint**

```
pytest -q
python -m ruff check .
```
Expected: all tests pass; ruff clean.

- [ ] **Push and open PR**

```bash
git push -u origin feat/code-switching-cloud-tbd
gh pr create --title "feat(code-switching): AssemblyAI + Speechmatics + OpenAI cloud paths [PR-C]" --body "$(cat <<'EOF'
## Summary

Cloud-path wiring for `language=='mixed'` on the three providers whose multilingual APIs were verified against current docs during implementation:

- **AssemblyAI**: enable `language_detection: true` AND switch `speech_model` to `"universal"` (multilingual model)
- **Speechmatics**: set `language: "auto"` and add `language_identification_config: {expected_languages: ["kk","ru","en"]}` (or equivalent — see commit message for verified field names)
- **OpenAI Whisper**: omit `language` form field (whisper-1 has no native code-switching; best-effort fallback)

Each task started with a research step documenting the verified API shape; see individual commit messages for vendor doc URLs.

## Test plan

- [x] `pytest -q` — all green including +3 new tests
- [x] `python -m ruff check .` — clean
- [x] Manual: each provider, short trilingual clip, `Смешанный` mode — confirm request shape doesn't 400
EOF
)"
```

- [ ] **Wait for review + merge before starting PR-D.**

---

## PR-D: Settings UI inline warning + Manual QA

**Branch:** `feat/code-switching-ui-warning` (created from `main` after PR-C merges).

**Goal:** When the user has `Смешанный (KZ+RU+EN)` selected as language AND the active cloud provider returns `supports_mixed() == False`, surface an inline warning under the provider dropdown in Settings so the user knows their combination won't work BEFORE they click Транскрибировать.

**Pre-task:**

```bash
git checkout main && git pull --ff-only origin main
git checkout -b feat/code-switching-ui-warning
```

---

### Task D.1: Add inline warning widget to Settings dialog

**Files:**
- Modify: `ui/dialogs/settings.py` (locate the provider dropdown / `cloud_provider` widget construction)

This task has no automated test (the project has minimal UI test infra; the spec's Manual QA #6 covers the behavior). The Implementation steps focus on widget construction + show/hide logic.

- [ ] **Step 1: Locate the cloud provider dropdown in `ui/dialogs/settings.py`**

```
grep -n "cloud_provider\|provider_var\|providers/_REGISTRY" ui/dialogs/settings.py | head -30
```

Identify the lines where the provider dropdown is created (likely a `CTkComboBox` or `CTkOptionMenu`).

- [ ] **Step 2: Add the warning label**

Just below the provider dropdown's `.pack()` / `.grid()` call, add a hidden warning label that the show/hide logic in Step 3 will toggle:

```python
# Inline warning shown when the selected provider can't handle the
# 'Смешанный (KZ+RU+EN)' language mode. Hidden by default; the
# language-change and provider-change callbacks (Step 3) toggle it.
self._mixed_warning_label = ctk.CTkLabel(
    parent_frame,                            # use whatever the dropdown's parent is
    text="",                                 # set dynamically in _update_mixed_warning
    text_color=theme.WARNING_FG,             # use existing theme token; if absent
                                             # use whatever red/orange the codebase
                                             # already uses for warnings (consult
                                             # theme.py for the right constant)
    font=ctk.CTkFont(size=11),
)
# Pack initially hidden — `pack_forget()` so it doesn't take layout space.
self._mixed_warning_label.pack(anchor="w", padx=8, pady=(0, 4))
self._mixed_warning_label.pack_forget()
```

Replace `parent_frame` with the actual parent widget reference used in the surrounding code (probably `self.scroll_frame` or `self.cloud_frame` — match what's already used for the dropdown).

- [ ] **Step 3: Add the show/hide logic**

Add a method to the Settings dialog class:

```python
def _update_mixed_warning(self) -> None:
    """Show inline warning when language='mixed' but the current provider
    can't service it. Called by both the language dropdown and provider
    dropdown change handlers."""
    from providers import get_provider_class  # adjust import to actual factory
    from ui.app.constants import LANGUAGES

    selected_lang_label = self.language_var.get()
    selected_provider_name = self.cloud_provider_var.get()

    lang_code = LANGUAGES.get(selected_lang_label)
    if lang_code != "mixed":
        self._mixed_warning_label.pack_forget()
        return

    try:
        # Construct without a real API key just to inspect supports_mixed().
        # Provider __init__ should be cheap (per providers/base.py docstring).
        provider_class = get_provider_class(selected_provider_name)
        instance = provider_class(api_key="")  # empty key OK for capability check
    except Exception:
        # If we can't even construct the provider, don't surface a warning —
        # the user will see a real error when they click Транскрибировать.
        self._mixed_warning_label.pack_forget()
        return

    if instance.supports_mixed():
        self._mixed_warning_label.pack_forget()
    else:
        self._mixed_warning_label.configure(
            text=(
                f"⚠ {selected_provider_name} не поддерживает "
                f"«Смешанный (KZ+RU+EN)». Выбери другой провайдер или язык."
            )
        )
        self._mixed_warning_label.pack(anchor="w", padx=8, pady=(0, 4))
```

If `providers/__init__.py` doesn't have `get_provider_class`, adapt this method to use whatever registry pattern is already in the codebase. Read `providers/__init__.py` to see the actual factory function name.

- [ ] **Step 4: Wire the callback to both dropdowns**

Find the language dropdown construction and the provider dropdown construction, and attach the callback. Pattern:

```python
self.language_var.trace_add("write", lambda *_: self._update_mixed_warning())
self.cloud_provider_var.trace_add("write", lambda *_: self._update_mixed_warning())
```

(If the dropdowns use `command=` callbacks instead of `trace_add` on a StringVar, attach there.)

Also call `self._update_mixed_warning()` once at the end of `__init__` so the initial state matches the loaded config.

- [ ] **Step 5: Manual smoke test**

```
python app.py
```
Then in the running app:
1. Open Settings.
2. Set language to `Смешанный (KZ+RU+EN)`.
3. Set provider to Deepgram → warning should appear under the provider dropdown.
4. Switch provider to Gladia → warning should disappear.
5. Switch language to `Русский` (with provider still Deepgram) → warning should disappear.

- [ ] **Step 6: Commit**

```bash
git add ui/dialogs/settings.py
git commit -m "feat(ui/settings): inline warning for incompatible mixed-mode pair

When language='Смешанный (KZ+RU+EN)' and the active provider's
supports_mixed() returns False (currently Deepgram only), show a
red warning label under the provider dropdown. Updates on both
language and provider changes."
```

---

### Task D.2: Manual QA execution

This task has no code; it executes the manual QA checklist from the spec
(`docs/superpowers/specs/2026-05-21-code-switching-kz-ru-en-design.md` — `Testing → Manual QA checklist`) and records results in the PR description.

- [ ] **Step 1: Prepare test audio**

You need three audio clips (~30s each is fine):
- **Pure-RU**: a clean Russian-only recording (any existing clip works)
- **Pure-RU duplicate** with `Смешанный` selected — same audio, different language setting
- **Trilingual**: KZ greeting (e.g. «Сәлеметсіз бе»), Russian body («Окей, давайте обсудим»), English technical terms (e.g. «Slack», «deployment», «Kubernetes»)

For the trilingual clip you can either record one quickly with the app's own recorder, or grab an existing one if available.

- [ ] **Step 2: Execute each manual check from the spec**

For each item in the spec's Manual QA section, run the scenario and record observed behavior. The 7 checks:

1. **Regression — pure RU + `Русский`**: transcript identical to baseline.
2. **Regression — pure RU + `Смешанный`**: quality no worse than baseline.
3. **Win — trilingual + `Смешанный` + Gladia**: measurably better than the same audio + `Русский` + Gladia.
4. **Local — trilingual + `Смешанный` + Whisper**: modest improvement vs `Русский` (prompt-effect only).
5. **Error — `Смешанный` + Deepgram**: friendly Russian error dialog, no crash.
6. **UI — Settings warning**: appears/disappears on dropdown changes (per Task D.1 Step 5 — already done above).
7. **Persistence — restart**: `config.json` with `"language": "Смешанный (KZ+RU+EN)"` loads correctly on next launch.

- [ ] **Step 3: Record results in PR description**

In the PR description, paste a filled-in version of the spec's Manual QA checklist with ☑/☒ marks and observed transcript snippets / screenshots for items 3, 4, and 5 (the user-visible quality and error behaviors).

If any check FAILS, do NOT open the PR — investigate and fix first. The most likely failure is item 3 (cloud quality regression in a provider) — if so, check the request shape in the failing provider against its docs again, the API may have evolved since PR-C was written.

---

### PR-D wrap-up

- [ ] **Run full suite + lint**

```
pytest -q
python -m ruff check .
```

- [ ] **Push and open PR**

```bash
git push -u origin feat/code-switching-ui-warning
gh pr create --title "feat(code-switching): Settings UI inline warning + manual QA [PR-D]" --body "$(cat <<'EOF'
## Summary

Final piece of Phase 1: a Settings-dialog inline warning that appears when the language is set to `Смешанный (KZ+RU+EN)` but the active provider's `supports_mixed()` is False. Plus completion of the manual QA checklist from the spec.

This closes Phase 1 of the code-switching design. Phase 2 (per-segment language detection for local Whisper, the only way to truly fix KZ inserts in RU local-Whisper recordings) is a separate spec and is NOT in this PR.

## Manual QA results

(Paste the filled-in checklist from Task D.2 Step 3 here, with transcript snippets / screenshots for items 3, 4, and 5.)

## Test plan

- [x] `pytest -q` — all green (no new automated tests added; UI test infra is minimal in this project)
- [x] `python -m ruff check .` — clean
- [x] Manual QA per spec — see results above
EOF
)"
```

- [ ] **After PR-D merges: update CLAUDE.md**

CLAUDE.md's "Active work / context" section should mention that Phase 1 of code-switching has shipped. Open a small docs follow-up PR (modeled on commit `fffe1a9 docs: update CLAUDE.md after F4-PR-2 closure`):

```bash
git checkout main && git pull --ff-only origin main
git checkout -b docs/claude-md-after-code-switching-phase1
# Edit CLAUDE.md → Active work / context → add a bullet for code-switching Phase 1
git commit -m "docs: update CLAUDE.md after code-switching Phase 1 ships"
git push -u origin docs/claude-md-after-code-switching-phase1
gh pr create --title "docs: update CLAUDE.md after code-switching Phase 1" --body "Records Phase 1 closure; Phase 2 (per-segment lang ID for local Whisper) still deferred."
```

---

## Plan self-review (already done by author)

**Spec coverage** — every spec section has a corresponding task:

- Architecture (sentinel-based dispatch) → Tasks A.1, A.3 (LANGUAGES + translator)
- Components table → all 17 file changes mapped to tasks A.1-D.1
- Data flow (UI → options → dispatch → provider/local) → covered by tasks A.3 (local) and B.1/B.2/C.1/C.2/C.3 (cloud)
- Error handling (Deepgram early-fail, Russian messages) → Task B.2
- Testing (12-14 new automated tests + Manual QA checklist) → embedded in each task + Task D.2
- Open questions (4 TBDs) → research steps in Tasks B.1, C.1, C.2, C.3
- Implementation phases (PR-A through PR-D) → matches plan structure

**Placeholder scan** — no `TBD`/`TODO`/`fill in later` left in steps. Research-step placeholders for vendor doc URLs are explicit research outputs, not unaddressed gaps. (Step explicitly says "if docs differ, update the test code".)

**Type consistency** — `_effective_whisper_language` is the function name throughout (introduced in A.3, no later task references a different name). `supports_mixed()` is the method name on `TranscriptionProvider` (A.4) and `DeepgramProvider` override (B.2). `_PROMPT_FRAMES["mixed"]` is the dict key in A.2 and the lookup site in A.3 stays unchanged because `_build_initial_prompt` already does `_PROMPT_FRAMES.get(language)`.

---

## Glossary

- **Foundation PR (PR-A)** — Lays down all four core pieces (LANGUAGES entry, prompt frame, translator, ABC method) so cloud-provider PRs can be written independently.
- **Known-API PR (PR-B)** — Providers whose multilingual API is documented and used in the existing codebase comment (Gladia `code_switching`) or whose limitation is documented in the existing code (Deepgram, "kk not in nova-3").
- **TBD-API PR (PR-C)** — Providers requiring fresh vendor-docs verification: AssemblyAI, Speechmatics, OpenAI Whisper.
- **Polish PR (PR-D)** — UI affordance for the new capability + manual QA confirmation that the user-visible behavior matches the spec.
- **Mixed-aware path** — The branch inside a provider's `_submit()` that runs when `options.language == "mixed"`.
