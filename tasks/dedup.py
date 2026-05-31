"""Task-dedup engine — decide if a new task duplicates a past SENT one.

Pure logic with no I/O in the body: the history loader and the LLM client
are injected (mirrors ``tasks/extractor.py``) so the whole module is
unit-testable without the filesystem or the network. PR-2 defines this;
PR-3 wires it into the Extract dialog. Nothing here is called by the
running app yet.

Pipeline (PR-3 caller shape):
    reg = build_sent_registry(list_history_entries(), load_tasks,
                              exclude_folder=current_folder)
    cands = find_candidates(new_task, reg, backend=b, container_id=c)
    if cands and cands[0][1] >= FUZZY_HIGH:
        match = cands[0][0]                      # confident, no LLM
    elif cands:                                  # borderline band
        match = disambiguate_via_llm(
            new_task, [c for c, _ in cands], openrouter_client, model)
    else:
        match = None                             # nothing close enough

Public API:
    SentTask                 — value type for a previously-sent task
    normalize_title(str)     — shared title normalization (exposed for tests)
    FUZZY_HIGH / FUZZY_LOW   — score thresholds (config-overridable in PR-3)
    build_sent_registry(...) — scan meeting history -> list[SentTask]
    find_candidates(...)     — fuzzy match within backend+container scope
    disambiguate_via_llm(...)— LLM resolves the borderline band
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from tasks.persistence import PersistenceError
from tasks.schema import TaskStatus

# Fuzzy-match score band (difflib.SequenceMatcher.ratio() on normalized
# titles). >=HIGH: confident duplicate, no LLM. LOW..HIGH: borderline ->
# ask the LLM. <LOW: not a match. PR-3 overrides these from config keys
# dedup_fuzzy_high / dedup_fuzzy_low.
FUZZY_HIGH = 0.82
FUZZY_LOW = 0.55

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+", re.UNICODE)


@dataclass(frozen=True)
class SentTask:
    """A task already created in a tracker on a past meeting.

    ``ref`` is the comment-addressable backend id (Linear node UUID /
    Trello full card id) copied from ``Task.backend_ref``; ``identifier``
    + ``url`` are the human badge/link for the UI. ``backend`` +
    ``container_id`` scope the match — a comment must land on the same
    team/board the new task would be created in.
    """
    title: str
    backend: str
    container_id: str
    ref: str
    identifier: str
    url: str
    meeting_name: str
    meeting_date: str


def normalize_title(title: str) -> str:
    r"""Lowercase, strip punctuation, collapse whitespace for fuzzy compare.

    ``\w`` is Unicode-aware (``re.UNICODE``) so Cyrillic / Kazakh letters
    survive — only punctuation and separators are removed. Empty/None-ish
    input returns "".
    """
    if not title:
        return ""
    lowered = title.lower()
    no_punct = _PUNCT_RE.sub(" ", lowered)
    return _WS_RE.sub(" ", no_punct).strip()


def build_sent_registry(
    entries: list[dict],
    load_tasks: Callable[[str], dict],
    *,
    exclude_folder: str | None = None,
) -> list[SentTask]:
    """Build the registry of previously-sent tasks from meeting history.

    ``entries`` come from ``utils.list_history_entries()`` (folder_path /
    folder_name / date_created). ``load_tasks`` is
    ``tasks.persistence.load_tasks`` injected so tests pass a fixture
    loader. A meeting contributes one ``SentTask`` per task with
    ``status == SENT`` and a non-empty ``backend_ref`` — older sent tasks
    predate ``backend_ref`` and have no comment-addressable id, so they
    cannot be commented on and are skipped. ``exclude_folder`` (the current
    meeting's ``folder_path``) never dedups against itself. Meetings with
    no/broken ``tasks.json`` (PersistenceError) are silently skipped — most
    meetings have no extracted tasks at all.
    """
    registry: list[SentTask] = []
    for entry in entries:
        folder = entry.get("folder_path")
        if not folder or folder == exclude_folder:
            continue
        try:
            loaded = load_tasks(folder)
        except PersistenceError:
            continue
        backend = loaded.get("backend") or "linear"
        container_id = loaded.get("team_id") or ""
        meeting_name = entry.get("folder_name") or ""
        meeting_date = entry.get("date_created") or ""
        for task in loaded.get("tasks", []):
            if task.status != TaskStatus.SENT or not task.backend_ref:
                continue
            registry.append(SentTask(
                title=task.title,
                backend=backend,
                container_id=container_id,
                ref=task.backend_ref,
                identifier=task.linear_issue_id or "",
                url=task.linear_issue_url or "",
                meeting_name=meeting_name,
                meeting_date=meeting_date,
            ))
    return registry
