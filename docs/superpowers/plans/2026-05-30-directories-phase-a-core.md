# Directory backend + context plumbing (Phase A core) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the non-UI foundation of the people/projects directory — the data model, on-disk store, the prompt-context renderer, per-run `segments.json` persistence, and an optional `context` parameter threaded into the protocol and task-extraction prompt builders.

**Architecture:** A new pure-stdlib `directory/` package (schema + atomic-JSON store + context renderer) modelled on `tasks/schema.py` and `tasks/persistence.py`. Two existing prompt builders (`tasks/protocol_generator.py`, `tasks/extractor.py`) gain a backward-compatible `context: str | None = None` parameter — when `None`, their output is byte-for-byte identical to today (regression-guarded). A new `utils.save_segments` is wired into the transcription run loop so the per-speaker timestamps survive on disk for later attribution.

**Tech Stack:** Python 3.10+, stdlib only (`dataclasses`, `json`, `uuid`, `datetime`, `pathlib`, `os`). Tests: `pytest`. Lint: `ruff`.

**Spec:** `docs/superpowers/specs/2026-05-30-directories-and-voice-id-design.md` (Part A, minus UI).

**Out of scope for this plan** (own follow-up plans): the «Справочники» CRUD dialog and the Extract-dialog attribution panel (Phase A UI); the `voiceid/` ONNX engine + invariant-#2 amendment (Phase B1). This plan introduces **no new dependency** and touches **no invariant**.

**Branch:** `feat/directory-backend`. One commit per task.

---

## File structure

| File | Responsibility |
|------|----------------|
| `directory/__init__.py` | package marker (convenience re-exports added in Task 7) |
| `directory/schema.py` | `Voiceprint`, `Person`, `Project` dataclasses + `to_dict`/`from_dict` |
| `directory/store.py` | `DirectoryStore`, `DirectoryError` — atomic JSON over `~/.audio-transcriber/directory.json` |
| `directory/context.py` | `render_meeting_context(people, project) -> str` (Russian prompt block) |
| `utils.py` | **+** `save_segments(folder, segments)` |
| `ui/app/transcription_mixin.py` | call `save_segments` after `create_history_entry` |
| `tasks/protocol_generator.py` | **+** `context` param in `build_prompt` + `generate` |
| `tasks/extractor.py` | **+** `context` param in `build_prompt` + `extract` |
| `CLAUDE.md` | add `directory/` to the "where things live" map |

---

## Task 1: directory schema (Person / Project / Voiceprint)

**Files:**
- Create: `directory/__init__.py`
- Create: `directory/schema.py`
- Test: `tests/test_directory_schema.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_directory_schema.py`:

```python
from directory.schema import Person, Project, Voiceprint


def test_person_roundtrip():
    p = Person(full_name="Айбек Нурланов", role="тимлид", project_ids=["pr1"])
    p2 = Person.from_dict(p.to_dict())
    assert p2.full_name == "Айбек Нурланов"
    assert p2.role == "тимлид"
    assert p2.project_ids == ["pr1"]
    assert p2.id == p.id


def test_person_from_dict_tolerates_missing_optional():
    p = Person.from_dict({"full_name": "Дана"})
    assert p.role == ""
    assert p.project_ids == []
    assert p.voiceprints == []
    assert p.tracker_member_id is None
    assert p.id  # auto-generated, non-empty


def test_person_autogenerates_distinct_ids():
    assert Person(full_name="A").id != Person(full_name="B").id


def test_voiceprint_roundtrip():
    vp = Voiceprint(vector=[0.1, 0.2, 0.3], source_meeting="2026-05-30_x")
    vp2 = Voiceprint.from_dict(vp.to_dict())
    assert vp2.vector == [0.1, 0.2, 0.3]
    assert vp2.source_meeting == "2026-05-30_x"


def test_person_roundtrip_with_voiceprints():
    p = Person(full_name="A", voiceprints=[Voiceprint(vector=[1.0, 2.0])])
    p2 = Person.from_dict(p.to_dict())
    assert len(p2.voiceprints) == 1
    assert p2.voiceprints[0].vector == [1.0, 2.0]


def test_project_roundtrip():
    pr = Project(name="Миграция", description="Перенос на Stripe")
    pr2 = Project.from_dict(pr.to_dict())
    assert pr2.name == "Миграция"
    assert pr2.description == "Перенос на Stripe"
    assert pr2.id == pr.id
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_directory_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'directory'`

- [ ] **Step 3: Create the package marker**

Create `directory/__init__.py`:

```python
"""People/projects directory (Phase A): schema, store, prompt-context renderer."""
```

- [ ] **Step 4: Implement the schema**

Create `directory/schema.py`:

```python
"""Data model for the people/projects directory.

Pure stdlib — no third-party deps, no I/O. Mirrors tasks/schema.py style:
mutable dataclasses with explicit to_dict / tolerant from_dict.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class Voiceprint:
    """One ECAPA voice embedding enrolled for a person (Part B fills these)."""

    vector: list[float]
    enrolled_at: str = field(default_factory=_now_iso)
    source_meeting: str = ""           # history folder name it was enrolled from

    def to_dict(self) -> dict:
        return {
            "vector": list(self.vector),
            "enrolled_at": self.enrolled_at,
            "source_meeting": self.source_meeting,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Voiceprint:
        return cls(
            vector=list(d.get("vector", [])),
            enrolled_at=d.get("enrolled_at") or _now_iso(),
            source_meeting=d.get("source_meeting", ""),
        )


@dataclass
class Person:
    """A meeting participant. project_ids reference Project.id (relation owner)."""

    full_name: str
    role: str = ""
    project_ids: list[str] = field(default_factory=list)
    voiceprints: list[Voiceprint] = field(default_factory=list)
    tracker_member_id: str | None = None
    id: str = field(default_factory=_new_id)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "full_name": self.full_name,
            "role": self.role,
            "project_ids": list(self.project_ids),
            "voiceprints": [vp.to_dict() for vp in self.voiceprints],
            "tracker_member_id": self.tracker_member_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Person:
        return cls(
            full_name=d["full_name"],
            role=d.get("role", ""),
            project_ids=list(d.get("project_ids", [])),
            voiceprints=[Voiceprint.from_dict(v) for v in d.get("voiceprints", [])],
            tracker_member_id=d.get("tracker_member_id"),
            id=d.get("id") or _new_id(),
            created_at=d.get("created_at") or _now_iso(),
            updated_at=d.get("updated_at") or _now_iso(),
        )


@dataclass
class Project:
    """A project with a description used to ground protocol/task prompts."""

    name: str
    description: str = ""
    tracker_ref: str | None = None     # optional Linear project / Trello board id
    id: str = field(default_factory=_new_id)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tracker_ref": self.tracker_ref,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Project:
        return cls(
            name=d["name"],
            description=d.get("description", ""),
            tracker_ref=d.get("tracker_ref"),
            id=d.get("id") or _new_id(),
            created_at=d.get("created_at") or _now_iso(),
            updated_at=d.get("updated_at") or _now_iso(),
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_directory_schema.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add directory/__init__.py directory/schema.py tests/test_directory_schema.py
git commit -m "feat(directory): people/projects/voiceprint schema"
```

---

## Task 2: directory store (atomic JSON CRUD)

**Files:**
- Create: `directory/store.py`
- Test: `tests/test_directory_store.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_directory_store.py`:

```python
import pytest

from directory.schema import Person, Project, Voiceprint
from directory.store import DirectoryError, DirectoryStore


def _fresh(tmp_path) -> DirectoryStore:
    s = DirectoryStore(path=tmp_path / "directory.json")
    s.load()
    return s


def test_load_missing_file_is_empty(tmp_path):
    s = _fresh(tmp_path)
    assert s.people() == []
    assert s.projects() == []


def test_upsert_person_persists_across_reload(tmp_path):
    path = tmp_path / "directory.json"
    s = DirectoryStore(path=path)
    s.load()
    s.upsert_person(Person(full_name="Айбек"))
    s2 = DirectoryStore(path=path)
    s2.load()
    assert [p.full_name for p in s2.people()] == ["Айбек"]


def test_delete_project_strips_refs_from_people(tmp_path):
    s = _fresh(tmp_path)
    pr = Project(name="Alpha")
    s.upsert_project(pr)
    p = Person(full_name="A", project_ids=[pr.id])
    s.upsert_person(p)
    s.delete_project(pr.id)
    assert s.projects() == []
    assert s.get_person(p.id).project_ids == []


def test_add_voiceprint_caps_at_five_dropping_oldest(tmp_path):
    s = _fresh(tmp_path)
    p = Person(full_name="A")
    s.upsert_person(p)
    for i in range(6):
        s.add_voiceprint(p.id, Voiceprint(vector=[float(i)]))
    vps = s.get_person(p.id).voiceprints
    assert len(vps) == 5
    assert vps[0].vector == [1.0]   # oldest (0.0) evicted
    assert vps[-1].vector == [5.0]


def test_add_voiceprint_unknown_person_raises(tmp_path):
    s = _fresh(tmp_path)
    with pytest.raises(DirectoryError):
        s.add_voiceprint("nope", Voiceprint(vector=[1.0]))


def test_malformed_file_raises_on_load(tmp_path):
    path = tmp_path / "directory.json"
    path.write_text("{ not json", encoding="utf-8")
    s = DirectoryStore(path=path)
    with pytest.raises(DirectoryError):
        s.load()


def _boom(*_a, **_k):
    raise ValueError("boom")


def test_save_failure_leaves_previous_file_intact(tmp_path, monkeypatch):
    import directory.store as store_mod

    path = tmp_path / "directory.json"
    s = DirectoryStore(path=path)
    s.load()
    s.upsert_person(Person(full_name="Good"))   # valid file on disk

    monkeypatch.setattr(store_mod.json, "dumps", _boom)
    with pytest.raises(ValueError):
        s.upsert_person(Person(full_name="Bad"))
    monkeypatch.undo()

    s2 = DirectoryStore(path=path)
    s2.load()
    assert [p.full_name for p in s2.people()] == ["Good"]
    assert not (tmp_path / ".directory.json.tmp").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_directory_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'directory.store'`

- [ ] **Step 3: Implement the store**

Create `directory/store.py`:

```python
"""On-disk store for the people/projects directory.

One combined file ~/.audio-transcriber/directory.json holding
{"people": [...], "projects": [...]}. Atomic write (tmp + os.replace),
mirroring tasks/persistence.py. Lives outside history/ and config.json so
voiceprint biometrics never ride the Google Drive backup.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from directory.schema import Person, Project, Voiceprint

FILENAME = "directory.json"
VOICEPRINT_CAP = 5


class DirectoryError(Exception):
    """Disk read/write or lookup failures bubble up as this."""


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _default_directory_path() -> Path:
    """~/.audio-transcriber/directory.json — beside the gdrive token cache.

    USERPROFILE/HOME env lookup mirrors gdrive/auth.py and stays test-friendly
    under monkeypatch.
    """
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or ".")
    return home / ".audio-transcriber" / FILENAME


class DirectoryStore:
    """In-memory people/projects keyed by id; every mutation writes the file."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else _default_directory_path()
        self._people: dict[str, Person] = {}
        self._projects: dict[str, Project] = {}

    def load(self) -> None:
        if not self.path.is_file():
            self._people, self._projects = {}, {}
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            raise DirectoryError(f"{FILENAME} malformed: {e}") from e
        self._people = {
            d["id"]: Person.from_dict(d) for d in data.get("people", [])
        }
        self._projects = {
            d["id"]: Project.from_dict(d) for d in data.get("projects", [])
        }

    # ── reads ──
    def people(self) -> list[Person]:
        return list(self._people.values())

    def projects(self) -> list[Project]:
        return list(self._projects.values())

    def get_person(self, person_id: str) -> Person | None:
        return self._people.get(person_id)

    def get_project(self, project_id: str) -> Project | None:
        return self._projects.get(project_id)

    # ── writes ──
    def upsert_person(self, person: Person) -> None:
        person.updated_at = _now_iso()
        self._people[person.id] = person
        self._save()

    def upsert_project(self, project: Project) -> None:
        project.updated_at = _now_iso()
        self._projects[project.id] = project
        self._save()

    def delete_person(self, person_id: str) -> None:
        self._people.pop(person_id, None)
        self._save()

    def delete_project(self, project_id: str) -> None:
        self._projects.pop(project_id, None)
        for person in self._people.values():
            if project_id in person.project_ids:
                person.project_ids = [
                    pid for pid in person.project_ids if pid != project_id
                ]
        self._save()

    def add_voiceprint(self, person_id: str, vp: Voiceprint) -> None:
        person = self._people.get(person_id)
        if person is None:
            raise DirectoryError(f"add_voiceprint: unknown person {person_id!r}")
        person.voiceprints.append(vp)
        if len(person.voiceprints) > VOICEPRINT_CAP:
            person.voiceprints = person.voiceprints[-VOICEPRINT_CAP:]
        person.updated_at = _now_iso()
        self._save()

    # ── persistence ──
    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "people": [p.to_dict() for p in self._people.values()],
            "projects": [pr.to_dict() for pr in self._projects.values()],
        }
        encoded = json.dumps(payload, ensure_ascii=False, indent=2)
        tmp = self.path.parent / f".{self.path.name}.tmp"
        try:
            tmp.write_text(encoded, encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as e:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise DirectoryError(f"Не удалось записать {FILENAME}: {e}") from e
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_directory_store.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add directory/store.py tests/test_directory_store.py
git commit -m "feat(directory): atomic JSON store with CRUD + voiceprint cap"
```

---

## Task 3: meeting-context renderer

**Files:**
- Create: `directory/context.py`
- Test: `tests/test_directory_context.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_directory_context.py`:

```python
from directory.context import render_meeting_context
from directory.schema import Person, Project


def test_full_context_exact():
    people = [
        Person(full_name="Айбек Нурланов", role="тимлид бэкенда"),
        Person(full_name="Дана Сапарова", role="продакт"),
    ]
    project = Project(name="Миграция биллинга", description="Перенос на Stripe")
    assert render_meeting_context(people, project) == (
        "=== КОНТЕКСТ ВСТРЕЧИ ===\n"
        "Проект: Миграция биллинга\n"
        "Описание: Перенос на Stripe\n"
        "\n"
        "Участники:\n"
        "- Айбек Нурланов — тимлид бэкенда\n"
        "- Дана Сапарова — продакт\n"
        "=== КОНЕЦ КОНТЕКСТА ==="
    )


def test_no_project_omits_project_lines():
    out = render_meeting_context([Person(full_name="A", role="r")], None)
    assert "Проект:" not in out
    assert out.startswith("=== КОНТЕКСТ ВСТРЕЧИ ===")
    assert "- A — r" in out


def test_empty_role_omits_dash():
    out = render_meeting_context([Person(full_name="Иван")], None)
    assert "- Иван" in out
    assert "—" not in out


def test_nothing_to_render_returns_empty_string():
    assert render_meeting_context([], None) == ""
    assert render_meeting_context([Person(full_name="   ")], None) == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_directory_context.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'directory.context'`

- [ ] **Step 3: Implement the renderer**

Create `directory/context.py`:

```python
"""Render the «КОНТЕКСТ ВСТРЕЧИ» block injected into protocol/task prompts.

Pure function, no I/O. Output is user-facing Russian (repo convention).
Returns "" when there is nothing to add, so callers pass context=None and the
downstream prompt is unchanged.
"""
from __future__ import annotations

from directory.schema import Person, Project


def render_meeting_context(people: list[Person], project: Project | None) -> str:
    lines: list[str] = []

    if project is not None and project.name.strip():
        lines.append(f"Проект: {project.name.strip()}")
        if project.description.strip():
            lines.append(f"Описание: {project.description.strip()}")
        lines.append("")  # blank line before participants

    named = [p for p in people if p.full_name.strip()]
    if named:
        lines.append("Участники:")
        for p in named:
            role = p.role.strip()
            if role:
                lines.append(f"- {p.full_name.strip()} — {role}")
            else:
                lines.append(f"- {p.full_name.strip()}")

    body = "\n".join(lines).strip()
    if not body:
        return ""
    return f"=== КОНТЕКСТ ВСТРЕЧИ ===\n{body}\n=== КОНЕЦ КОНТЕКСТА ==="
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_directory_context.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add directory/context.py tests/test_directory_context.py
git commit -m "feat(directory): render meeting-context prompt block"
```

---

## Task 4: persist segments.json + wire into the run loop

**Files:**
- Modify: `utils.py` (add `save_segments`)
- Modify: `ui/app/transcription_mixin.py:38` (import) and `:253-262` (call)
- Test: `tests/test_utils_save_segments.py`, `tests/test_transcription_mixin_segments.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_utils_save_segments.py`:

```python
import json

from utils import save_segments


def test_save_segments_writes_json(tmp_path):
    segs = [{"start": 0.0, "end": 1.5, "text": "hi", "speaker": "SPEAKER_00"}]
    save_segments(str(tmp_path), segs)
    data = json.loads((tmp_path / "segments.json").read_text(encoding="utf-8"))
    assert data == segs


def test_save_segments_none_is_noop(tmp_path):
    save_segments(str(tmp_path), None)
    assert not (tmp_path / "segments.json").exists()


def test_save_segments_empty_list_writes_empty(tmp_path):
    save_segments(str(tmp_path), [])
    data = json.loads((tmp_path / "segments.json").read_text(encoding="utf-8"))
    assert data == []
```

Create `tests/test_transcription_mixin_segments.py` (source-text only — importing
`ui.app` pulls in `sounddevice`/PortAudio, absent on Linux CI):

```python
from pathlib import Path


def test_run_loop_persists_segments_after_history_entry():
    src = Path("ui/app/transcription_mixin.py").read_text(encoding="utf-8")
    assert "save_segments(self._last_history_folder" in src
    assert "self._transcriber.last_segments" in src


def test_run_loop_imports_save_segments():
    src = Path("ui/app/transcription_mixin.py").read_text(encoding="utf-8")
    import_lines = [ln for ln in src.splitlines() if ln.startswith("from utils import")]
    assert import_lines, "expected a 'from utils import' line"
    assert any("save_segments" in ln for ln in import_lines)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_utils_save_segments.py tests/test_transcription_mixin_segments.py -v`
Expected: FAIL — `ImportError: cannot import name 'save_segments' from 'utils'` (and the source-text asserts fail)

- [ ] **Step 3: Add `save_segments` to `utils.py`**

Append to `utils.py` (after `create_history_entry`; `json` and `os` are already
imported at the top of the file):

```python
def save_segments(folder: str, segments: list[dict] | None) -> None:
    """Atomically write raw transcription segments to <folder>/segments.json.

    The audio is copied into the meeting folder by create_history_entry, but the
    per-speaker timestamps would otherwise be lost — they are what later
    speaker-attribution slices on. No-op when segments is None (e.g. a provider
    that returned nothing to cache).
    """
    if segments is None:
        return
    target = os.path.join(folder, "segments.json")
    tmp = os.path.join(folder, ".segments.json.tmp")
    encoded = json.dumps(segments, ensure_ascii=False, indent=2)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(encoded)
    os.replace(tmp, target)
```

- [ ] **Step 4: Wire it into the run loop**

In `ui/app/transcription_mixin.py`, extend the utils import (line 38):

```python
from utils import create_history_entry, save_config, save_segments
```

Then, inside `_on_complete`, immediately after the `create_history_entry(...)`
assignment block (after line 262, still inside `if self._audio_path:`), add:

```python
            # Persist raw segments so post-transcription speaker attribution
            # (directory feature) can slice per-speaker audio later. The audio
            # is copied into the folder, but the speaker timestamps are not.
            if self._last_history_folder and self._transcriber is not None:
                save_segments(
                    self._last_history_folder, self._transcriber.last_segments,
                )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_utils_save_segments.py tests/test_transcription_mixin_segments.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add utils.py ui/app/transcription_mixin.py tests/test_utils_save_segments.py tests/test_transcription_mixin_segments.py
git commit -m "feat(history): persist segments.json for later speaker attribution"
```

---

## Task 5: `context` param in the protocol prompt

**Files:**
- Modify: `tasks/protocol_generator.py` (`build_prompt` signature + body; `generate` thread-through)
- Test: `tests/test_protocol_generator.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_protocol_generator.py`:

```python
from tasks.protocol_generator import build_prompt as _build_prompt


def test_build_prompt_injects_context_before_transcript():
    out = _build_prompt(
        "T", ["Айбек"], "2026-05-30", "ru",
        context="=== КОНТЕКСТ ВСТРЕЧИ ===\nПроект: X\n=== КОНЕЦ КОНТЕКСТА ===",
    )
    assert "Проект: X" in out
    assert out.index("Проект: X") < out.index("=== ТРАНСКРИПТ ===")


def test_build_prompt_context_none_matches_legacy():
    with_default = _build_prompt("T", ["Айбек"], "2026-05-30", "ru")
    with_none = _build_prompt("T", ["Айбек"], "2026-05-30", "ru", context=None)
    assert with_default == with_none
    assert "КОНТЕКСТ ВСТРЕЧИ" not in with_none
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_protocol_generator.py -k context -v`
Expected: FAIL — `TypeError: build_prompt() got an unexpected keyword argument 'context'`

- [ ] **Step 3: Add the `context` parameter**

In `tasks/protocol_generator.py`, change the `build_prompt` signature (currently
ends `lang: str | None,` → `) -> str:`) to add a trailing parameter:

```python
def build_prompt(
    transcript: str,
    speakers: list[str],
    meeting_date: str,
    lang: str | None,
    context: str | None = None,
) -> str:
```

Then in its body, replace the `return (...)` block with one that inserts the
context block ahead of the transcript marker (empty string when `context` is
falsy → byte-identical to today):

```python
    context_block = f"{context}\n\n" if context else ""

    return (
        f"Дата встречи: {meeting_date or '(не указана)'}\n"
        f"Заявленные участники: {speakers_str}\n"
        f"Язык транскрипта: {lang_label}\n"
        f"\n"
        f"{context_block}"
        f"=== ТРАНСКРИПТ ===\n"
        f"{transcript}\n"
        f"=== КОНЕЦ ТРАНСКРИПТА ===\n"
        f"\n"
        f"Извлеки 5 блоков по формату из системной инструкции."
    )
```

Then thread it through `generate`: add `context: str | None = None` to the
`generate(...)` signature (after the `lang` parameter, before `model`) and pass
it into the call:

```python
    user_message = build_prompt(transcript, speakers, meeting_date, lang, context=context)
```

Document the new `generate` parameter in its docstring Args:

```
        context: optional pre-rendered «КОНТЕКСТ ВСТРЕЧИ» block (participant
            profiles + project description) injected into the user message.
            None reproduces the pre-directory prompt exactly.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_protocol_generator.py -v`
Expected: PASS (existing tests + 2 new)

- [ ] **Step 5: Commit**

```bash
git add tasks/protocol_generator.py tests/test_protocol_generator.py
git commit -m "feat(protocol): optional meeting-context injection in the prompt"
```

---

## Task 6: `context` param in the task-extraction prompt

**Files:**
- Modify: `tasks/extractor.py` (`build_prompt` signature + user message; `extract` thread-through)
- Test: `tests/test_tasks_extractor.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tasks_extractor.py`:

```python
from tasks.extractor import build_prompt as _ex_build_prompt


def test_extractor_build_prompt_injects_context():
    msgs = _ex_build_prompt("transcript", [], [], "ru", context="CTXBLOCK")
    user = msgs[1]["content"]
    assert "CTXBLOCK" in user
    assert user.index("CTXBLOCK") < user.index("Meeting transcript")


def test_extractor_build_prompt_context_none_unchanged():
    msgs = _ex_build_prompt("transcript", [], [], "ru")
    assert msgs[1]["content"].startswith("Meeting transcript")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_tasks_extractor.py -k context -v`
Expected: FAIL — `TypeError: build_prompt() got an unexpected keyword argument 'context'`

- [ ] **Step 3: Add the `context` parameter**

In `tasks/extractor.py`, change the `build_prompt` signature to add a trailing
parameter:

```python
def build_prompt(
    transcript: str,
    members: list[dict],
    labels: list[dict],
    lang: str | None,
    context: str | None = None,
) -> list[dict]:
```

Then replace the `user = (...)` assignment (currently starting
`f"Meeting transcript ({lang_hint}):\n\n"`) with a context-prefixed version:

```python
    context_block = f"{context}\n\n" if context else ""
    user = (
        f"{context_block}"
        f"Meeting transcript ({lang_hint}):\n\n"
        f"{transcript}\n\n"
        "Return only the JSON object."
    )
```

Then thread it through `extract`: add `context: str | None = None` to the
`extract(...)` keyword-only parameters (alongside `members`/`labels`) and pass it
into the `build_prompt` call (currently `messages = build_prompt(transcript, members, labels, lang)`):

```python
    messages = build_prompt(transcript, members, labels, lang, context=context)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_tasks_extractor.py -v`
Expected: PASS (existing tests + 2 new)

- [ ] **Step 5: Commit**

```bash
git add tasks/extractor.py tests/test_tasks_extractor.py
git commit -m "feat(extract): optional meeting-context injection in the prompt"
```

---

## Task 7: package exports, docs, full gate

**Files:**
- Modify: `directory/__init__.py` (convenience re-exports)
- Modify: `CLAUDE.md` ("where things live" row)

- [ ] **Step 1: Add convenience re-exports**

Replace `directory/__init__.py` with:

```python
"""People/projects directory (Phase A): schema, store, prompt-context renderer."""
from directory.context import render_meeting_context
from directory.schema import Person, Project, Voiceprint
from directory.store import DirectoryError, DirectoryStore

__all__ = [
    "Person",
    "Project",
    "Voiceprint",
    "DirectoryStore",
    "DirectoryError",
    "render_meeting_context",
]
```

- [ ] **Step 2: Verify the package imports cleanly**

Run: `python -c "import directory; print(directory.__all__)"`
Expected: prints the list of exported names, no traceback.

- [ ] **Step 3: Document where the new package lives**

In `CLAUDE.md`, under the "Where things live" table, add a row after the
"Task extraction" row:

```markdown
| People/projects directory (Phase A) | `directory/` (`schema`, `store` — atomic JSON at `~/.audio-transcriber/directory.json`, `context` — prompt-context renderer). Used to ground protocol + task prompts with real names/roles/project descriptions. |
```

- [ ] **Step 4: Run the full test + lint gate**

Run: `pytest`
Expected: PASS — baseline 333 + 26 new (6 schema + 7 store + 4 context + 3 save_segments + 2 mixin source-text + 2 protocol + 2 extractor) = 359 green (adjust if your local baseline differs).

Run: `python -m ruff check .`
Expected: clean (no findings).

- [ ] **Step 5: Commit**

```bash
git add directory/__init__.py CLAUDE.md
git commit -m "feat(directory): public exports + CLAUDE.md where-things-live entry"
```

---

## Self-review (completed during plan authoring)

**Spec coverage (Part A, non-UI):**
- Person/Project/Voiceprint data model → Task 1 ✓
- Combined `directory.json` atomic store, CRUD, `delete_project` cascade, voiceprint cap → Task 2 ✓
- `render_meeting_context` Russian block → Task 3 ✓
- `segments.json` per-run persistence → Task 4 ✓
- `context` param in protocol prompt → Task 5 ✓
- `context` param in task prompt → Task 6 ✓
- Privacy (D-G): store path `~/.audio-transcriber/` outside `history/`+`config.json` → Task 2 (`_default_directory_path`) ✓
- **Deferred (own plans):** «Справочники» dialog + Extract attribution panel (Phase A UI); `voiceid/` engine + invariant-#2 amendment (Phase B1). Explicitly out of scope above.

**Placeholder scan:** none — every code/test step contains complete content.

**Type consistency:** `DirectoryStore` methods (`load`, `people`, `projects`,
`get_person`, `get_project`, `upsert_person`, `upsert_project`, `delete_person`,
`delete_project`, `add_voiceprint`) are referenced consistently across Task 2
tests and impl. `render_meeting_context(people, project)` signature matches
between Task 3 impl/tests and the Task 5/6 injection contract (a pre-rendered
`str`). `save_segments(folder, segments)` matches between Task 4 impl, tests, and
the run-loop call site. The protocol/extractor `context: str | None = None`
trailing-keyword shape is identical in both Task 5 and Task 6.
