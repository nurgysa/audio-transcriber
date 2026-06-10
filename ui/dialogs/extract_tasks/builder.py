"""Widget-tree constructor for the Extract-Tasks dialog.

Extracted from ``ui/dialogs/extract_tasks/__init__.py`` (widget-tree
split, 2026-06-10 spec). Same contract as ``ui/app/builder.py`` /
``ui/dialogs/settings_builder.py``: free functions take the live dialog,
create widgets, and set captured refs on it under their original names.
Handlers, workers (extraction/dedup/containers), and state stay on
``ExtractTasksDialog``.

Import discipline (cycle guard): may import theme, ui.widgets and the
sibling ``.constants`` / ``.task_row`` — never the package ``__init__``.
"""

from __future__ import annotations

import customtkinter as ctk

from theme import BLUE, BLUE_DIM, BORDER, FONT, INPUT_BG, TEXT_PRIMARY
from ui.widgets import label

from .constants import _NO_SELECTION


def rebuild_context_participants(dialog, checked_ids: set[str]) -> None:
    """Render a checkbox per directory person, ticking checked_ids."""
    for w in dialog._context_participants_frame.winfo_children():
        w.destroy()
    dialog._context_person_vars = {}
    people = dialog._dir_store.people()
    if not people:
        label(
            dialog._context_participants_frame,
            "(справочник пуст — добавьте людей в «Справочники»)",
        ).grid(row=0, column=0, padx=4, pady=2, sticky="w")
        return
    for i, p in enumerate(people):
        var = ctk.BooleanVar(value=p.id in checked_ids)
        dialog._context_person_vars[p.id] = var
        text = p.full_name + (f" — {p.role}" if p.role else "")
        ctk.CTkCheckBox(
            dialog._context_participants_frame, text=text, variable=var,
            fg_color=BLUE, hover_color=BLUE_DIM, text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(family=FONT, size=12),
            checkbox_height=16, checkbox_width=16,
        ).grid(row=i, column=0, padx=4, pady=1, sticky="w")


def build_speaker_rows(dialog) -> None:
    """Render one «Спикер N → person» dropdown per diarized speaker label.

    Reads <meeting>/segments.json and maps raw labels to the same
    friendly «Спикер N» the transcript shows (via _build_speaker_map).
    No segments / no diarization / empty directory → a muted hint and
    no rows (pure manual mapping is impossible; the dialog still works).
    """
    # _build_speaker_map is transcript_format-internal but stable: it is the
    # single source of the «Спикер N» labels the transcript shows and is
    # already covered by test_transcript_format. Reuse keeps the panel's
    # labels identical to the rendered transcript.
    from transcript_format import _build_speaker_map
    from utils import load_segments

    for w in dialog._speaker_rows_frame.winfo_children():
        w.destroy()
    dialog._speaker_row_vars = {}
    dialog._speaker_friendly = {}

    label_map = _build_speaker_map(load_segments(dialog._history_folder))
    people = dialog._dir_store.people()
    if not label_map or not people:
        hint = (
            "(нет данных о спикерах)"
            if not label_map
            else "(справочник пуст — добавьте людей в «Справочники»)"
        )
        label(dialog._speaker_rows_frame, hint).grid(
            row=0, column=0, padx=4, pady=2, sticky="w",
        )
        return

    names = [_NO_SELECTION] + [p.full_name for p in people]
    for i, (raw, friendly) in enumerate(label_map.items()):
        dialog._speaker_friendly[raw] = friendly
        var = ctk.StringVar(value=_NO_SELECTION)
        dialog._speaker_row_vars[raw] = var
        label(dialog._speaker_rows_frame, friendly).grid(
            row=i, column=0, padx=(4, 8), pady=2, sticky="w",
        )
        ctk.CTkComboBox(
            dialog._speaker_rows_frame, variable=var, values=names,
            width=220, height=28, state="readonly",
            font=ctk.CTkFont(family=FONT, size=12),
            border_color=BORDER, button_color=BORDER,
            fg_color=INPUT_BG, text_color=TEXT_PRIMARY,
            command=lambda _v, r=raw: dialog._on_speaker_bound(r),
        ).grid(row=i, column=1, padx=0, pady=2, sticky="w")
