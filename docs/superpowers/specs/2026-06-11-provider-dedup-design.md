# Provider dedup — shared transport layer for the 4 cloud STT providers

**Date:** 2026-06-11
**Status:** approved (Вариант 3 of the 2026-06-10 improvement audit)
**Scope:** `providers/` package + its tests. No UI, no `Transcriber`, no `base.py` contract changes.

## Motivation

The 2026-06-10 audit measured 65–80 % duplication across the four provider
modules (`assemblyai.py` 430 LOC, `deepgram.py` 302, `gladia.py` 345,
`speechmatics.py` 428) and located the worst cyclomatic complexity in the
codebase there (`deepgram.transcribe` C901 = 14). PR #133 added a fourth
near-identical `validate_key` to each provider, raising the pattern count
to the point where every future provider change must be hand-replicated
four times. This refactor lifts the *transport* duplication into one shared
module while deliberately leaving the *domain* differences (payload
building, response mapping) where they are.

Line references below are against `main` @ `9d31d61`.

## Duplication inventory (verified by reading, not grep)

| # | Pattern | Sites | Degree |
|---|---------|-------|--------|
| 1 | `_check_cancel` (Event check + lazy `TranscriptionCancelled` import) | aai:351, dg:175, gl:284, sm:262 | byte-identical ×4 |
| 2 | `_guess_content_type` (ext→MIME map) | dg:185, gl:294, sm:272 | byte-identical ×3 |
| 3 | `__init__` empty-key check («API-ключ X не задан…») | aai:58, dg:52, gl:50, sm:44 | identical except provider name |
| 4 | `validate_key` (cheap GET, 401/403 → «отклонил ключ») | aai:67, dg:60, gl:59, sm:53 | identical except URL/headers/name |
| 5 | Poll loop (90-min deadline, pretty status map, 0.25 s sliced sleep, JSON guard) | aai `_poll`:270, gl `_poll`:229, sm `_wait_for_job`:163 | structurally identical; knobs differ (see PollSpec) |
| 6 | HTTP error idiom (`RequestException`→«Сеть не отвечает при…», 401→«отклонил ключ», `not ok`→`failed (N): text[:300]`, JSON parse→«Неожиданный ответ») | ~14 request sites across all 4 | template-identical |
| 7 | Streaming upload generator with 0–70 % progress band | aai `_upload._gen`:147, dg `transcribe._gen`:118 | near-identical ×2 |
| 8 | `_cancel_remote` (best-effort DELETE) | aai:331, sm:250 | same intent; aai version is better (narrow except + warning log) |

Not duplication (left alone): `_submit`/`_build_params`/`_build_config`
payload builders, `_to_segments` adapters, `_extract_language` — these
encode real per-API differences.

## Design

### New module: `providers/_common.py` (~220 LOC)

Single shared module, underscore-private to the package. All `requests.*`
calls made on behalf of providers live here, which also gives the test
suite **one canonical patch target**: `providers._common.requests`.

```python
UPLOAD_CHUNK = 5 * 1024 * 1024   # moves from assemblyai.py / deepgram.py

def check_cancel(cancel_event) -> None
    # Lifts pattern 1. Same lazy `from transcriber import TranscriptionCancelled`.

def guess_content_type(path: str) -> str
    # Lifts pattern 2 verbatim.

def require_key(api_key: str | None, provider: str) -> str
    # Lifts pattern 3. Strips and returns the key; raises ProviderError
    # («API-ключ {provider} не задан. Открой Настройки → Облако и вставь ключ.»)

def request(method: str, url: str, *, provider: str, action_ru: str,
            action_en: str, timeout: float, **kwargs) -> requests.Response
    # Lifts pattern 6. Wraps requests.request():
    #   RequestException → ProviderError(f"Сеть не отвечает при {action_ru}: {e}")
    #   401/403          → ProviderError(f"{provider} отклонил ключ (401). "
    #                       "Проверь API-ключ в Настройках → Облако.")
    #                      ("(401)" stays hardcoded — matches the #133
    #                       validate_key precedent and existing test matches)
    #   not r.ok         → ProviderError(f"{provider} {action_en} failed "
    #                       f"({r.status_code}): {r.text[:300]}")
    # Returns the Response on 2xx.

def parse_json(resp, *, provider: str, context: str | None = None) -> dict
    # ValueError → ProviderError(f"Неожиданный ответ {provider}"
    #              + (f" на {context}" if context else "") + f": {resp.text[:300]}")

def extract_json_key(resp, key: str, *, provider: str, context: str) -> Any
    # parse_json + KeyError → same «Неожиданный ответ…» message.

@dataclass
class PollSpec:
    url: str
    headers: dict
    provider: str                          # display name for messages
    interval_s: float                      # aai/gladia 3.0, speechmatics 5.0
    extract_status: Callable[[dict], str | None]
    done_statuses: frozenset[str]
    error_statuses: frozenset[str]
    extract_error: Callable[[dict], str]
    pretty: dict[str, str]                 # status → Russian status line
    max_wait_s: float = 90 * 60

def poll(spec: PollSpec, on_status, cancel_event) -> dict
    # Lifts pattern 5: monotonic deadline («{provider} не вернул результат
    # за {N} минут…»), GET via request() (action_ru="опросе", action_en="poll"),
    # its own JSON guard (f"{provider} вернул не-JSON ответ при опросе
    # ({code}): {text[:300]}" — kept distinct; test_providers_poll_json_guard
    # pins it), pretty-status dedup via last_status, terminal handling
    # («{provider} вернул ошибку: {spec.extract_error(payload)}»),
    # 0.25 s sliced sleep with check_cancel. Returns the final payload.

def file_stream(path: str, *, cancel_event, on_progress, band: float = 70.0)
    # Lifts pattern 7: chunked read generator, progress 0..band %.

def cancel_remote(url: str, headers: dict, *, provider: str) -> None
    # Lifts pattern 8, AssemblyAI flavour wins: narrow
    # requests.RequestException + logger.warning («job may stay billable»).
    # Kills speechmatics.py's bare `except Exception: pass` (one of the 7
    # uncommented broad excepts flagged by the audit).
    # NOTE: providers KEEP thin `_cancel_remote(job_id)` methods that build
    # the URL and delegate here — tests call `p._cancel_remote("id")`
    # directly (test_providers_assemblyai.py:145,155), and transcribe()
    # call sites stay readable.

def validate_via_get(url: str, *, headers: dict, provider: str,
                     params: dict | None = None) -> dict
    # Lifts pattern 4 body. Self-contained: does NOT route through
    # request() — its ≥400 template differs from request()'s "failed"
    # template, and it ships in PR-1 before request() exists.
    # Keeps the exact #133 message templates:
    # network → «Сеть не отвечает при проверке ключа: {e}»,
    # 401/403 → «{provider} отклонил ключ (401). Проверь API-ключ…»,
    # ≥400    → «{provider}: проверка ключа не удалась ({code}): {text[:300]}».
    # Returns {} on 2xx.
```

### What each provider keeps

- Its `transcribe()` workflow orchestration (shrinks because plumbing moves
  out, but the call order / progress bands stay literally per-provider:
  AAI 0–70 upload + poll, Gladia 5→50→100, SM 5→50→100, DG 0–70→100).
- Payload builders (`_submit` bodies, `_build_params`, `_build_config`) and
  response adapters (`_to_segments`, `_extract_language`, `_normalise_speaker`).
- Its `PollSpec` knobs, defined at the `_poll` call site. The callables keep
  response-shape knowledge in the provider module:
  - AAI: status `payload.get("status")`, done `{"completed"}`, error
    `{"error"}`, detail `payload.get("error", "<no detail>")`, 3.0 s.
  - Gladia: status `payload.get("status")`, done `{"done"}`, error
    `{"error"}`, detail `error_code or error or "<no detail>"`, 3.0 s.
  - SM: status `(payload.get("job") or {}).get("status") or
    payload.get("status")`, done `{"done"}`, error
    `{"rejected", "deleted", "expired"}`, detail
    `(payload.get("job") or {}).get("errors") or "<no detail>"`, 5.0 s.
  - Pretty maps stay per-provider dicts (SM has "running", others
    "processing").
- A 3-line `validate_key()` override calling `validate_via_get` with its
  URL/headers/params. SM's `_fetch_transcript` becomes a `request()` +
  `parse_json` call (action_ru «получении транскрипта», action_en
  "transcript fetch").

### What does NOT change

- **`base.py` is untouched.** The ABC contract, the default-refuse
  `validate_key` from #133 (so `_StubProvider` subclasses and unwired
  providers still read as "not supported"), `supports_mixed` /
  `supports_diarization` semantics — all as-is.
- **`transcribe()` does NOT become a base-class template method.** The
  workflows genuinely differ (DG single sync call; SM submit+wait+fetch
  with cancel-on-failure; AAI cancel-on-poll-failure). Forcing a template
  here is over-engineering; explicit non-goal.
- No changes outside `providers/` and `tests/`.

## Behavior changes (the honest list)

1. **403 is now treated like 401 on transcribe-path calls** (previously only
   `validate_key` did; transcribe paths showed a generic `failed (403)`).
   Message improvement, low risk.
2. **Short 401 messages in `_submit` paths** («AssemblyAI отклонил ключ
   (401).») **become the long form** with «Проверь API-ключ в Настройках →
   Облако.» — one template.
3. **Response-body truncation unified to `[:300]`** (validate_key used
   `[:200]`).
4. **Deepgram's non-ok message** changes from «Deepgram вернул ошибку
   (N): …» to the majority template «Deepgram transcribe failed (N): …»
   (action_en="transcribe"). The affected test match in
   `test_providers_deepgram.py` is updated in the same commit.
5. **SM `_cancel_remote`** gains a warning log and narrows `except
   Exception` → `except requests.RequestException` (behavior on network
   failure is identical: swallow; now visible in app.log).

Everything else is byte-preserved: «Сеть не отвечает при …» wordings, the
90-minute deadline message, per-provider pretty status lines, poll
intervals, progress bands.

## Test strategy

**Constraint discovered up front:** the existing mocked-HTTP net (~47 KB
across `test_providers_{assemblyai,deepgram,gladia,speechmatics,validate,
poll_json_guard}.py`) patches `providers.<module>.requests.<verb>`. Moving
the HTTP calls breaks those patch targets silently (mocks stop
intercepting; tests would hit the network or fail oddly).

- **Re-target mechanically** to `providers._common.requests.<verb>`:
  34 literal `providers.<module>.requests` patch sites across 5 files,
  plus 3 parametrized `f"{module}.requests.get"` expressions in
  `test_providers_validate.py` (one-line module-list change there). All
  behavioral assertions (ProviderError match patterns, segment shapes,
  status sequences) stay — they are the refactor's real safety net.
- **New `tests/test_providers_common.py`:** direct units for `request()`
  (network / 401 / 403 / non-ok / 2xx), `poll()` (terminal, error status,
  deadline, non-JSON, pretty dedup, cancel), `file_stream` (band math,
  cancel mid-stream), `require_key`, `parse_json` / `extract_json_key`,
  `cancel_remote` (warns, never raises), `guess_content_type`.
- **Absence guard** (same spirit as `test_widget_tree_split`): source-text
  test asserting the four provider modules no longer contain
  `except requests.RequestException` or `time.sleep` — the idiom lives only
  in `_common.py`. Cheap protection against duplicate resurrection.

## Verification

- Full suite (baseline ≈ 773) + `python -m ruff check .` on every commit
  (run with `py -3` — plain `python` is shadowed by the Hermes venv).
- **Live AssemblyAI smoke after PR-2** via `cli.core` (the #130 smoke
  pattern: key read in-process from `~/.audio-transcriber`, never printed)
  plus live `validate_key` good + garbage (the #133 pattern).
- Deepgram / Gladia / Speechmatics stay mock-pinned (no live keys) — same
  caveat as #133, stated in the PR body.

## PR slicing (2 serial PRs, each merged before the next starts)

- **PR-1 `refactor(providers): lift identical helpers to _common`** —
  `check_cancel`, `guess_content_type`, `require_key`, `cancel_remote`,
  `validate_via_get`, `file_stream`, `UPLOAD_CHUNK`. Zero behavior change
  except list items 3 and 5 above. Test impact: re-target
  `test_providers_validate.py` patches and the two AAI `requests.delete`
  patches; add the `_common` units for the lifted helpers.
- **PR-2 `refactor(providers): unify HTTP transport + poll loop`** —
  `request()`, `parse_json`/`extract_json_key`, `PollSpec` + `poll()`;
  providers shrink (~−250 LOC net, `deepgram.transcribe` C901 14 → ~6).
  Mass patch re-target + absence guard + remaining `_common` units +
  behavior-change items 1, 2, 4. Live AAI smoke before merge.

## Risks

| Risk | Mitigation |
|------|------------|
| Patch re-target misses a site → test silently hits network | After re-target, grep tests for `providers\.(assemblyai\|deepgram\|gladia\|speechmatics)\.requests` must return 0 hits |
| Russian message drift breaks UI expectations | The honest-list above is exhaustive; everything else byte-preserved; match-pattern tests pin the templates |
| `PollSpec` callables capture wrong response shapes | Per-provider poll tests already feed recorded payload shapes; they stay green unmodified except patch targets |
| Mixed-language / diarization regressions | No `_submit`/`_to_segments` logic is touched at all |
