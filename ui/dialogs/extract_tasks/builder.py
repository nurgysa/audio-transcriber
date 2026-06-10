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
from ui.widgets import label, tonal_button

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


def build_form(dialog) -> None:
    """Build the right-side form. Variables are owned by the form
    and bound to the selected task via _bind_form_to / _form_to_task."""
    f = dialog._form_panel

    # StringVar/BooleanVar instances (re-bound on selection change).
    dialog._var_title       = ctk.StringVar()
    dialog._var_priority    = ctk.StringVar(value="none")
    dialog._var_assignee    = ctk.StringVar(value="(нет)")
    dialog._var_due_date    = ctk.StringVar()

    # ── Autofill-from-text section (Phase 6.5, Söyle-friendly) ──
    # User dictates a free-form description (via Söyle or by typing)
    # into this textbox; clicking the button below runs the text
    # through the LLM (extract_one_task) and overwrites the form
    # fields. Sits at the TOP of the form so it's the first thing
    # the user sees when they click + Добавить on a fresh task.
    label(f, "Подсказка для AI (можно надиктовать через Söyle)").grid(
        row=0, column=0, padx=12, pady=(12, 2), sticky="w",
    )
    dialog._textbox_autofill_hint = ctk.CTkTextbox(
        f, wrap="word", height=64,
        font=ctk.CTkFont(family=FONT, size=12),
        fg_color=INPUT_BG, text_color=TEXT_PRIMARY,
    )
    dialog._textbox_autofill_hint.grid(
        row=1, column=0, padx=12, pady=(0, 6), sticky="ew",
    )
    dialog._btn_autofill = tonal_button(
        f, text="Заполнить из текста",
        command=dialog._on_autofill_clicked, width=200,
    )
    dialog._btn_autofill.grid(row=2, column=0, padx=12, pady=(0, 14), sticky="w")

    row = 3
    label(f, "Заголовок").grid(row=row, column=0, padx=12, pady=(12, 2), sticky="w")
    row += 1
    dialog._entry_title = ctk.CTkEntry(
        f, textvariable=dialog._var_title, height=36,
        font=ctk.CTkFont(family=FONT, size=13),
        fg_color=INPUT_BG, text_color=TEXT_PRIMARY, border_color=BORDER,
    )
    dialog._entry_title.grid(row=row, column=0, padx=12, pady=(0, 8), sticky="ew")
    dialog._var_title.trace_add("write", lambda *_: dialog._on_form_changed())

    row += 1
    label(f, "Приоритет").grid(row=row, column=0, padx=12, pady=(0, 2), sticky="w")
    row += 1
    dialog._dropdown_priority = ctk.CTkOptionMenu(
        f, variable=dialog._var_priority,
        values=["none", "low", "medium", "high", "urgent"],
        command=lambda _v: dialog._on_form_changed(),
        fg_color=INPUT_BG, text_color=TEXT_PRIMARY, button_color=BORDER,
        font=ctk.CTkFont(family=FONT, size=12),
    )
    dialog._dropdown_priority.grid(row=row, column=0, padx=12, pady=(0, 8), sticky="ew")

    row += 1
    label(f, "Исполнитель").grid(row=row, column=0, padx=12, pady=(0, 2), sticky="w")
    row += 1
    dialog._dropdown_assignee = ctk.CTkOptionMenu(
        f, variable=dialog._var_assignee,
        values=["(нет)"],
        command=lambda _v: dialog._on_form_changed(),
        fg_color=INPUT_BG, text_color=TEXT_PRIMARY, button_color=BORDER,
        font=ctk.CTkFont(family=FONT, size=12),
    )
    dialog._dropdown_assignee.grid(row=row, column=0, padx=12, pady=(0, 8), sticky="ew")

    row += 1
    label(f, "Метки").grid(row=row, column=0, padx=12, pady=(0, 2), sticky="w")
    row += 1
    # For Phase 6.2, labels are displayed as a comma-joined string in an
    # entry. Toggle UI (chips with X buttons) is post-6.4 polish.
    dialog._var_labels_csv = ctk.StringVar()
    dialog._entry_labels = ctk.CTkEntry(
        f, textvariable=dialog._var_labels_csv, height=36,
        font=ctk.CTkFont(family=FONT, size=12),
        fg_color=INPUT_BG, text_color=TEXT_PRIMARY, border_color=BORDER,
        placeholder_text="метка1, метка2 (только из team-labels)",
    )
    dialog._entry_labels.grid(row=row, column=0, padx=12, pady=(0, 8), sticky="ew")
    dialog._var_labels_csv.trace_add("write", lambda *_: dialog._on_form_changed())

    row += 1
    label(f, "Дата (YYYY-MM-DD)").grid(row=row, column=0, padx=12, pady=(0, 2), sticky="w")
    row += 1
    dialog._entry_due = ctk.CTkEntry(
        f, textvariable=dialog._var_due_date, height=36,
        font=ctk.CTkFont(family=FONT, size=12),
        fg_color=INPUT_BG, text_color=TEXT_PRIMARY, border_color=BORDER,
        placeholder_text="напр. 2026-05-15",
    )
    dialog._entry_due.grid(row=row, column=0, padx=12, pady=(0, 8), sticky="ew")
    dialog._var_due_date.trace_add("write", lambda *_: dialog._on_form_changed())

    row += 1
    label(f, "Описание").grid(row=row, column=0, padx=12, pady=(0, 2), sticky="w")
    row += 1
    f.grid_rowconfigure(row, weight=1)
    dialog._textbox_description = ctk.CTkTextbox(
        f, wrap="word", height=80,
        font=ctk.CTkFont(family=FONT, size=12),
        fg_color=INPUT_BG, text_color=TEXT_PRIMARY,
    )
    dialog._textbox_description.grid(row=row, column=0, padx=12, pady=(0, 12), sticky="nsew")
    # CTkTextbox doesn't take a textvariable — we read it on save.
    dialog._textbox_description.bind("<<Modified>>", dialog._on_description_modified)
