# Directories (people + projects) + voice identification — design

- **Date:** 2026-05-30
- **Status:** Approved (brainstorming) — pending implementation plan
- **Scope:** A local **directory** of people and projects, used to **ground
  the protocol and task-extraction prompts** with real names, roles and
  project descriptions; plus a local **voice-identification** layer that maps
  each meeting's diarized speakers back to directory people automatically
  (enrollment on first sighting, auto-ID thereafter).

## Summary

Today the protocol generator receives `speakers=[]` and the LLM sees faceless
`Спикер 1 / Спикер 2`. Task extraction grounds assignees only on **tracker**
members (Linear/Trello), unrelated to who actually spoke. The output quality
is capped by this missing context.

This feature adds two cooperating pieces:

- **Part A — Directory + context injection** (no biometrics). A CRUD store of
  **people** (ФИО / role / projects) and **projects** (name / description).
  After a meeting the human maps each diarized speaker to a directory person
  (or creates one). The mapping lets us feed the protocol and task prompts a
  **context block**: real participant names + roles + the meeting's project
  description. This is the primary quality lever and touches no invariant.

- **Part B — Voice identification** (local ONNX). On enrollment we store a
  compact **voiceprint** (≈192-dim ECAPA-TDNN embedding) per person. On the
  next meeting we embed each speaker's audio and cosine-match against the
  directory, so the speaker→person mapping is **pre-filled automatically**;
  the human only confirms or corrects. Part B is what makes Part A's context
  appear without manual work every time.

The goal, in the user's words: **«улучшить качество протокола и задач, давая
контекст через описание проектов и профиль людей»** — voice is the
auto-fill of "who is who", context is the payoff.

## Goals

- A people directory: ФИО, role (responsibilities), project membership, voiceprints.
- A project catalog: name + description (first-class entity, not free-text tags).
- Manual "Спикер N → person" attribution after a meeting; create-person-on-the-fly.
- Inject participant profiles + project description into the **protocol** prompt
  (`protocol_generator`) and **task** prompt (`extractor`) as runtime context.
- Local voiceprint enrollment + cosine auto-identification on later meetings.
- Optional person→tracker-member link so task assignees can be auto-routed.
- All storage local JSON; biometrics never leave the machine by default.

## Non-goals

- No cloud voice API, no speaker **diarization** of our own — we consume the
  cloud providers' existing `speaker` labels; we only *identify* who each
  cluster is. (Diarization stays the STT provider's job.)
- No vector database — matching is brute-force cosine over a handful of
  recurring colleagues (small N).
- No torch / CUDA / pyannote / faster-whisper / ctranslate2 (invariant #2
  stands; see the amendment — only CPU **onnxruntime** is added).
- No long-term audio retention for biometrics — only the compact voiceprint
  persists; audio is read once at enrollment from the meeting folder.
- No re-attribution of meetings transcribed **before** this feature ships
  (they have no persisted segments — see `segments.json`).

## Key design decisions

| # | Decision | Rationale |
|---|----------|-----------|
| **D-A** | One embedding per speaker = **concat their segments, cap ~45 s, single ECAPA embedding** | Simple, robust; 45 s is well past ECAPA's saturation. Averaging N slices (rejected) adds cost for marginal gain at this N. |
| **D-B** | Attribution runs as a **step inside the Extract dialog**, before protocol generation | That dialog already owns the history folder + protocol/task pipeline and is invoked exactly when the user wants outputs. Avoids a popup interrupting the transcription run loop. |
| **D-C** | ECAPA ONNX model is **bundled into the .exe** | Desktop app must work offline; first-run download (rejected) needs network and complicates PyInstaller packaging of the data file. |
| **D-D** | One combined store file `~/.audio-transcriber/directory.json` `{people:[…], projects:[…]}` | Person→Project is a cross-reference; one atomic write keeps the two collections consistent. Two files (rejected) put the reference across a file boundary. |
| **D-E** | One **«Справочники»** dialog with two tabs (Люди / Проекты) | One entry point, shared window chrome; mirrors how the data relates (people reference projects). |
| **D-F** | **Amend invariant #2** to permit local **CPU ONNX** inference | onnxruntime-CPU is none of the banned libs and reintroduces none of their pain (no CUDA DLLs, no VRAM, no teardown SIGSEGV). Documented carve-out, not a silent violation. |
| **D-G** | `directory.json` lives in `~/.audio-transcriber/` (outside `history/` and `config.json`) | Biometric PII must not ride the Google Drive backup (which zips `history/` + redacts `config.json`). Placing it beside `gdrive-token.json` keeps it local by construction. |
| **D-H** | **Phase A first, then B.** Part B gated behind `voiceid_enabled` (default false) | Part A delivers most of the value and breaks no invariant — shippable to first clients immediately. B turns on once the model is bundled + smoke-tested. |

## Part A — directory + context injection

### Data model — `directory/schema.py`

Frozen dataclasses with `to_dict` / `from_dict` (mirrors `tasks/schema.py`):

```
Voiceprint:
  vector        : list[float]   # 192 floats (ECAPA)
  enrolled_at   : str           # ISO
  source_meeting: str           # history folder name it was enrolled from

Person:
  id            : str           # uuid4 hex
  full_name     : str           # ФИО
  role          : str           # responsibilities (free text)
  project_ids   : list[str]     # references Project.id (D-D)
  voiceprints   : list[Voiceprint]   # 0..N (Part B); empty in A-only mode
  tracker_member_id : str | None     # optional Linear/Trello member id
  created_at / updated_at : str

Project:
  id            : str           # uuid4 hex
  name          : str
  description   : str           # the grounding payload
  tracker_ref   : str | None    # optional Linear project / Trello board id
  created_at / updated_at : str
```

Relationship lives **only** on `Person.project_ids` (D-D). "Who is in project
X" is derived by scanning people — no dual write, no drift.

### Store — `directory/store.py`

`DirectoryStore` over `~/.audio-transcriber/directory.json`. Atomic write
(dump to `.directory.json.tmp` → `os.replace`), exactly like
`tasks/persistence.py`. `DirectoryError(Exception)` for I/O failures.

```
load() -> None                         # parse file (or start empty)
people() -> list[Person]
projects() -> list[Project]
get_person(id) / get_project(id)
upsert_person(p) / upsert_project(pr)  # set updated_at, write atomically
delete_person(id) / delete_project(id) # delete_project also strips the id
                                       #   from every Person.project_ids
add_voiceprint(person_id, vp)          # cap N (default 5), drop oldest
```

`delete_project` cascades the reference cleanup so no person points at a
dangling project id.

### Context rendering — `directory/context.py`

Pure function, no I/O, produces the Russian block injected into prompts:

```
render_meeting_context(
    people: list[Person],
    project: Project | None,
) -> str
```

Output (user-facing → Russian, per the repo convention):

```
=== КОНТЕКСТ ВСТРЕЧИ ===
Проект: <name>
Описание: <description>

Участники:
- <ФИО> — <role>
- <ФИО> — <role>
=== КОНЕЦ КОНТЕКСТА ===
```

Omits the `Проект` lines when `project is None`; omits a participant's `— role`
when role is empty; returns `""` when there is nothing to add (callers then
pass `context=None` and behaviour is identical to today).

### Integration into the protocol prompt — `tasks/protocol_generator.py`

The format contract stays in the cached `_SYSTEM_PROMPT`. New context is
**runtime data → user message** (preserves OpenRouter prompt-caching).

- `build_prompt(transcript, speakers, meeting_date, lang, context=None)` — new
  trailing optional `context: str | None`. When present, it is inserted ahead
  of the `=== ТРАНСКРИПТ ===` block.
- `generate(..., context=None)` — threads it through.
- `speakers` is now populated with **real ФИО** of identified people (fallback
  `Спикер N` for any unattributed speaker), so the `## participants` block the
  system prompt already describes is grounded.

### Integration into the task prompt — `tasks/extractor.py`

- `build_prompt(transcript, members, labels, lang, context=None)` — same new
  optional `context`. `members` (tracker assignees) is unchanged; the context
  block adds project description + participant profiles so action items are
  framed in the project's terms.
- `extract(*, …, context=None)` — threads it through.
- When an identified person has `tracker_member_id`, the dialog can hint the
  LLM (or post-map) the right assignee instead of guessing — see UI wiring.

### Per-run persistence

| File (in the history/meeting folder) | Content | Producer |
|---|---|---|
| `segments.json` **(new)** | raw `last_segments` `[{start,end,text,speaker?}]` | transcription run loop |
| `speakers.json` **(new)** | `{ "SPEAKER_00": "<person_id>", … }` + `project_id` | Extract dialog attribution step |

`segments.json` is what makes attribution (and re-attribution) possible after
the run: the audio is already copied into the folder by
`utils.create_history_entry`, but the speaker timestamps are currently lost.
Both writes reuse the atomic tmp-rename helper.

## Part B — voice identification (local ONNX)

### Engine — `voiceid/` package

```
voiceid/embedder.py    # ONNX ECAPA-TDNN wrapper
voiceid/matcher.py     # cosine + threshold bands
voiceid/attribution.py # orchestration: segments+audio → suggestions
```

**`embedder.py`** — `Embedder.embed(samples: np.ndarray) -> np.ndarray[192]`.
onnxruntime + the model are **lazy-loaded via the sentinel pattern** (declare
`_session = None` at module top; populate inside the first call) so
`import voiceid.embedder` stays cheap and tests can `patch` the session
cleanly — same trick as `gdrive/backup.py::DriveClient`. CPU
`InferenceSession`; deterministic, single-threaded.

**`matcher.py`** — `cosine(a, b) -> float` and:

```
classify(score: float,
         auto_threshold: float,
         suggest_threshold: float) -> Literal["auto","suggest","unknown"]
```

The threshold band logic is the one **deliberately-left-to-the-user**
contribution (see "Open decision"). Defaults seed `config.json`
(`voiceid_auto_threshold` / `voiceid_suggest_threshold`).

**`attribution.py`** — the cross-cutting flow (imports `directory.store`;
`directory/` never imports `voiceid/`):

```
suggest_speakers(
    audio_path: str,
    segments: list[dict],
    store: DirectoryStore,
    auto_threshold: float,
    suggest_threshold: float,
) -> list[SpeakerSuggestion]
```

`SpeakerSuggestion = {label, best_person_id|None, score, decision}`.

Steps per distinct `speaker` label:
1. `audio_io.ensure_wav(audio_path)` → 16 kHz mono (recordings already are;
   imported MP3/M4A get decoded). Read once.
2. Concatenate that speaker's segment spans, cap ~45 s (D-A), slice samples.
3. `embedder.embed(slice)` → vector.
4. Brute-force `cosine` vs every voiceprint of every person; keep the best.
5. `matcher.classify(best)` → `auto` / `suggest` / `unknown`.

### Enrollment policy

On the user confirming "SPEAKER_xx = person P" in the panel:

- Persist the mapping to `speakers.json`.
- **Add this meeting's embedding to P** when it is new information — i.e. P had
  no voiceprint yet, **or** the match was below `auto_threshold` (a correction).
  Skip when it was already a high-confidence auto-hit (redundant).
- `store.add_voiceprint` caps at 5 per person (drop oldest) to bound file size
  and keep matching cheap.

This is a reasonable default; the cap and the "enroll-on-correction" rule are
tunable and called out as secondary tuning knobs alongside the thresholds.

## UI surfaces

### «Справочники» dialog — `ui/dialogs/directory/` (D-E)

A new CTk dialog, two tabs:

- **Люди:** list + add/edit/delete; fields ФИО, обязанности, проекты
  (multi-select from the project catalog), voiceprint count (read-only), and
  an optional "Участник трекера" link. Buttons «Добавить» / «Сохранить» /
  «Удалить».
- **Проекты:** list + add/edit/delete; fields Название, Описание, optional
  tracker ref.

Entry point: a button in Settings (and/or the main window) — «Справочники».
All colours from `theme.py` (no naked hex — enforced by
`tests/test_theme_invariants.py`).

### Speaker-attribution step — inside the Extract dialog (D-B)

Rendered before the «Сгенерировать протокол» action. Reads `segments.json`
from the history folder; if `voiceid_enabled`, calls
`voiceid.attribution.suggest_speakers` to pre-fill.

One row per speaker label:

```
Спикер 1   [Айбек Нурланов ▼]  ✓ авто (0.82)
Спикер 2   [— выбрать —     ▼]  • новый голос
```

The dropdown lists: the auto/suggested person first, then all directory
people, then «+ Создать нового…» (opens a quick inline person form) and
«Оставить как есть». A meeting-level «Проект: [катáлог ▼]» selector sits above,
defaulting to the union of the chosen participants' projects.

On «Применить»: write `speakers.json` (label→person_id + project_id), run
enrollment policy, then build `context = render_meeting_context(people,
project)` and pass it (plus real-name `speakers`) into
`protocol_generator.generate(...)` and `extractor.extract(...)`.

When `voiceid_enabled` is false (Part A only), the same panel appears with no
pre-fill — pure manual mapping. The context injection still works.

## Architecture & components

### New files

| File | Purpose |
|------|---------|
| `directory/__init__.py` | package marker |
| `directory/schema.py` | `Person`, `Project`, `Voiceprint` dataclasses |
| `directory/store.py` | `DirectoryStore`, `DirectoryError`, atomic JSON |
| `directory/context.py` | `render_meeting_context(...)` |
| `voiceid/__init__.py` | package marker |
| `voiceid/embedder.py` | ONNX ECAPA wrapper (lazy/sentinel) |
| `voiceid/matcher.py` | cosine + `classify` thresholds |
| `voiceid/attribution.py` | `suggest_speakers(...)` orchestration |
| `ui/dialogs/directory/__init__.py` | «Справочники» dialog (tabs) |
| `assets/models/ecapa.onnx` | bundled model (~20–25 MB) |

### Touched files

| File | Change |
|------|--------|
| `tasks/protocol_generator.py` | optional `context` param in `build_prompt` + `generate`; real-name `speakers` |
| `tasks/extractor.py` | optional `context` param in `build_prompt` + `extract` |
| `ui/dialogs/extract_tasks/__init__.py` | attribution step; build context; replace `speakers=[]` at the `generate` call (~666) with real names; write `speakers.json` |
| `ui/app/transcription_mixin.py` | after a run, dump `transcriber.last_segments` → `<folder>/segments.json` |
| `ui/dialogs/settings.py` | «Справочники» button; «Голосовая идентификация» toggle (`voiceid_enabled`) + threshold inputs |
| `config.example.json` | `voiceid_enabled:false`, `voiceid_auto_threshold`, `voiceid_suggest_threshold` |
| `requirements.txt` | `+onnxruntime` (CPU), `+numpy` pin (already transitive via soundfile) |
| `CLAUDE.md` | invariant #2 amendment (D-F); add directory/voiceid to the "where things live" map |
| `tests/` | new suites (below) |

## Invariant #2 amendment (D-F)

Proposed wording added under invariant #2 in `CLAUDE.md`:

> **Exception (2026-05-30, directories + voice-ID feature):** local **CPU
> ONNX** inference via `onnxruntime` is permitted for voice-embedding
> extraction (`voiceid/`). It is explicitly **not** torch/CUDA/pyannote/
> faster-whisper/ctranslate2 and reintroduces none of their failure modes
> (no CUDA DLLs, no VRAM pressure, no teardown SIGSEGV). The ban on those five
> libraries stands. Any *new* local-inference dependency beyond onnxruntime
> still requires a discussion first.

## Privacy / backup (D-G)

`directory.json` (voiceprints = biometric PII) sits in `~/.audio-transcriber/`,
outside both `history/` (zipped into the Drive backup) and `config.json`
(redacted + uploaded). It therefore **stays local by construction** — no code
change to `gdrive/backup.py` needed. `speakers.json` inside a meeting folder
*does* ride the backup, but it holds only opaque `person_id` references, no
vectors. Documented as an explicit decision; revisit only if the user later
wants directory sync.

## Build / dependencies

- `onnxruntime` CPU wheel (~15–20 MB). No GPU variant.
- `assets/models/ecapa.onnx` (~20–25 MB) bundled via `audio_transcriber.spec`
  `datas`; resolve its path with the same `sys._MEIPASS`-aware pattern
  `utils.py` already uses for bundled vendor assets (ffmpeg / icons, `utils.py:39-65`).
- onnxruntime ships native DLLs; verify PyInstaller collects them (a hook
  usually exists) during the Task-4 packaging smoke. `.exe` grows ~40 MB —
  acceptable.
- numpy is already pulled in transitively; pin it explicitly so the frozen
  build is reproducible.

## Testing strategy

Mocked/pure unit tests (UI suites must **not** import `ui.app` on Linux CI —
PortAudio absent; use source-text or `spec_from_file_location` per
`test_ui_constants.py`):

- `test_directory_schema.py` — `to_dict`/`from_dict` round-trip for all three
  types; unknown-key tolerance.
- `test_directory_store.py` — CRUD; atomic write (poison `json.dumps`, assert
  no partial file); `delete_project` strips refs; voiceprint cap/eviction.
- `test_directory_context.py` — rendered block with/without project, empty
  role, empty directory → `""`.
- `test_voiceid_matcher.py` — cosine math; `classify` band edges
  (auto/suggest/unknown boundaries); tie-break determinism.
- `test_voiceid_embedder.py` — onnxruntime session **mocked**; asserts input
  shaping (16 kHz mono float32) and a (192,) output; lazy-load only on first call.
- `test_voiceid_attribution.py` — embedder + store mocked; speaker-slice
  concatenation + 45 s cap; suggestion decisions; multi-speaker.
- `test_protocol_generator.py` / `test_extractor.py` — extend: `context`
  string lands in the user message; `context=None` reproduces today's prompt
  byte-for-byte (regression guard).

Baseline `pytest` is 333 green; this adds ~35–45 tests. `ruff check .` clean.

## Manual smoke (required before merge)

1. **Directory:** open «Справочники», create a project with a description and
   two people, assign them to the project, link one to a tracker member.
2. **Part A:** transcribe a meeting; in Extract, map Спикер 1/2 to the two
   people, pick the project → generate protocol → confirm the `## participants`
   block shows **real ФИО** and the theses reference the project domain;
   confirm a task's assignee matches the linked tracker member.
3. **Part B enroll:** with `voiceid_enabled`, confirm the mapping enrolls
   voiceprints (directory shows count 1).
4. **Part B auto-ID:** transcribe a *second* meeting with the same voices →
   the attribution panel pre-fills «✓ авто» with the right people.
5. **Offline + frozen:** repeat 3–4 from the PyInstaller `.exe` with no network
   to prove the bundled model loads (`sys._MEIPASS` path).
6. **Privacy:** run a Google Drive backup → confirm `directory.json` is **not**
   in the uploaded zip.

## Risks & open questions

- **ONNX model sourcing/licence.** ECAPA-TDNN (e.g. SpeechBrain
  `spkrec-ecapa-voxceleb`) exported to ONNX, or a pre-exported
  permissively-licensed model. Confirm licence allows bundling before picking
  the exact file. (Spec-level TODO for the plan's pre-flight.)
- **Diarization quality ceiling.** Auto-ID is only as good as the provider's
  speaker clustering; over-/under-clustering shifts work back to the human
  panel — acceptable, the panel is the safety net.
- **Imported-audio format.** MP3/M4A meetings need `ensure_wav` before
  embedding; recordings (16 kHz mono WAV) are already ECAPA-ready.
- **Cross-talk / short turns.** A speaker with <~3 s total audio yields a weak
  embedding; `classify` should land such cases in `suggest`/`unknown`, never
  `auto` (threshold tuning covers this).

## Phasing (D-H)

1. **Phase A1** — `directory/` package + «Справочники» dialog (CRUD only).
2. **Phase A2** — `segments.json` persistence + Extract attribution panel
   (manual) + context injection into protocol & extractor. *Ships the quality
   win; no onnxruntime yet.*
3. **Phase B1** — `voiceid/` engine + bundled model + enrollment + auto-ID
   pre-fill behind `voiceid_enabled`; invariant #2 amendment lands here.

Each phase is its own PR(s) per the one-concern rule.

## Out of scope

- Cloud/multi-device sync of the directory; team-shared directories.
- Our own diarization; speaker separation of overlapping speech.
- Voiceprint export/import; biometric consent UX beyond local-only storage.
- Auto-creating tracker projects/boards from catalog projects.

## Open decision (left to the user — learning mode)

`voiceid/matcher.py::classify` — the auto/suggest/unknown band logic (~8 lines)
is a product judgement, not boilerplate: too strict ⇒ the panel nags every
meeting; too loose ⇒ words get attributed to the wrong colleague in a protocol
that may drive real tasks. The signature is specified above and the band values
are seeded as placeholders in `config.json` (calibrated during B1 smoke); the
body is written by the user during Phase B1, with the scaffold (signature,
docstring, TODO) prepared in advance.
