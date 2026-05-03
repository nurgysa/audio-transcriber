"""Hotword dictionary editor dialog."""

from __future__ import annotations

import customtkinter as ctk

from theme import (
    BG,
    BLUE,
    BLUE_DIM,
    BORDER,
    FONT,
    INPUT_BG,
    RED,
    SURFACE,
    SURFACE_BRIGHT,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)
from utils import save_config


class TermsDialog(ctk.CTkToplevel):
    """Dialog for managing saved hotwords/terms (CRUD)."""

    def __init__(self, parent, config: dict, on_save):
        super().__init__(parent)
        self.title("Словарь терминов")
        self.geometry("480x520")
        self.configure(fg_color=BG)
        self.transient(parent)
        self.grab_set()

        self._config = config
        self._on_save = on_save
        self._terms: list[str] = list(config.get("hotwords", []))

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # --- Header ---
        header = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=48)
        header.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(
            header, text="Словарь терминов",
            font=ctk.CTkFont(family=FONT, size=16, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=20, pady=12)

        # --- Add row ---
        add_frame = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=12)
        add_frame.grid(row=1, column=0, padx=16, pady=(12, 8), sticky="ew")
        add_frame.grid_columnconfigure(0, weight=1)

        self._entry_var = ctk.StringVar()
        self._entry = ctk.CTkEntry(
            add_frame, textvariable=self._entry_var, height=36,
            corner_radius=10, border_color=BORDER, border_width=1,
            fg_color=INPUT_BG, text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(family=FONT, size=13),
            placeholder_text="Новый термин...",
        )
        self._entry.grid(row=0, column=0, padx=(12, 8), pady=12, sticky="ew")
        self._entry.bind("<Return>", lambda e: self._add_term())

        ctk.CTkButton(
            add_frame, text="Добавить", width=100, height=36, corner_radius=18,
            font=ctk.CTkFont(family=FONT, size=13, weight="bold"),
            fg_color=BLUE, hover_color=BLUE_DIM, text_color="#FFFFFF",
            command=self._add_term,
        ).grid(row=0, column=1, padx=(0, 12), pady=12)

        # --- Terms list ---
        self._list_frame_outer = ctk.CTkScrollableFrame(
            self, fg_color=SURFACE, corner_radius=12,
        )
        self._list_frame_outer.grid(row=2, column=0, padx=16, pady=8, sticky="nsew")
        self._list_frame_outer.grid_columnconfigure(0, weight=1)

        self._render_list()

        # --- Footer ---
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, padx=16, pady=(4, 14), sticky="ew")

        self._lbl_count = ctk.CTkLabel(
            footer, text="", font=ctk.CTkFont(family=FONT, size=12),
            text_color=TEXT_SECONDARY,
        )
        self._lbl_count.grid(row=0, column=0, sticky="w")
        self._update_count()

        footer.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            footer, text="Готово", width=100, height=36, corner_radius=18,
            font=ctk.CTkFont(family=FONT, size=13, weight="bold"),
            fg_color=BLUE, hover_color=BLUE_DIM, text_color="#FFFFFF",
            command=self._close,
        ).grid(row=0, column=1, sticky="e")

    def _render_list(self):
        for widget in self._list_frame_outer.winfo_children():
            widget.destroy()

        if not self._terms:
            ctk.CTkLabel(
                self._list_frame_outer, text="Нет сохранённых терминов",
                font=ctk.CTkFont(family=FONT, size=13),
                text_color=TEXT_SECONDARY,
            ).grid(row=0, column=0, pady=20)
            return

        for i, term in enumerate(self._terms):
            row = ctk.CTkFrame(
                self._list_frame_outer,
                fg_color=SURFACE_BRIGHT,
                corner_radius=10,
                height=40,
            )
            row.grid(row=i, column=0, padx=4, pady=3, sticky="ew")
            row.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                row, text=term, anchor="w",
                font=ctk.CTkFont(family=FONT, size=13),
                text_color=TEXT_PRIMARY,
            ).grid(row=0, column=0, padx=12, pady=8, sticky="ew")

            ctk.CTkButton(
                row, text="✕", width=32, height=32, corner_radius=16,
                font=ctk.CTkFont(family=FONT, size=14),
                fg_color="transparent", hover_color=BORDER,
                text_color=RED, command=lambda idx=i: self._delete_term(idx),
            ).grid(row=0, column=1, padx=(0, 8), pady=4)

    def _add_term(self):
        term = self._entry_var.get().strip()
        if not term:
            return
        if term not in self._terms:
            self._terms.append(term)
            self._save()
            self._render_list()
            self._update_count()
        self._entry_var.set("")

    def _delete_term(self, index: int):
        self._terms.pop(index)
        self._save()
        self._render_list()
        self._update_count()

    def _update_count(self):
        self._lbl_count.configure(text=f"Терминов: {len(self._terms)}")

    def _save(self):
        self._config["hotwords"] = self._terms
        save_config(self._config)
        self._on_save()

    def _close(self):
        self.grab_release()
        self.destroy()
