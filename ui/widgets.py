"""Shared CustomTkinter widget factories.

Three styles of button (primary blue, tonal blue-on-surface, danger red),
a card frame, a labeled text helper, the option-menu used everywhere for
dropdowns, and a text entry. Keeps the theme palette confined to one
import surface — palette changes don't ripple through every dialog.
"""

from __future__ import annotations

import customtkinter as ctk

from theme import (
    BG,
    BLUE,
    BLUE_DIM,
    BLUE_SURFACE,
    BORDER,
    FONT,
    INPUT_BG,
    SURFACE,
    SURFACE_BRIGHT,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)


def card(parent, **kwargs) -> ctk.CTkFrame:
    """A surface-tinted rounded frame used for grouping controls."""
    return ctk.CTkFrame(
        parent, fg_color=SURFACE, corner_radius=16, border_width=0, **kwargs,
    )


def label(parent, text, size=13, color=TEXT_SECONDARY, **kwargs) -> ctk.CTkLabel:
    """Plain text label using the project font and the secondary color by default."""
    return ctk.CTkLabel(
        parent, text=text,
        font=ctk.CTkFont(family=FONT, size=size),
        text_color=color, **kwargs,
    )


def primary_button(parent, text, command, width=160, **kwargs) -> ctk.CTkButton:
    """Solid blue pill button — for the main action in a frame (Транскрибировать, Готово)."""
    return ctk.CTkButton(
        parent, text=text, command=command, width=width,
        height=40, corner_radius=20,
        font=ctk.CTkFont(family=FONT, size=13, weight="bold"),
        fg_color=BLUE, hover_color=BLUE_DIM, text_color="#FFFFFF",
        **kwargs,
    )


def tonal_button(parent, text, command, width=130, **kwargs) -> ctk.CTkButton:
    """Quieter blue-on-surface button — for secondary actions (Открыть, Копировать)."""
    return ctk.CTkButton(
        parent, text=text, command=command, width=width,
        height=40, corner_radius=20,
        font=ctk.CTkFont(family=FONT, size=13),
        fg_color=BLUE_SURFACE, hover_color=SURFACE_BRIGHT,
        text_color="#8AB4F8",
        **kwargs,
    )


def danger_button(parent, text, command, width=130, **kwargs) -> ctk.CTkButton:
    """Solid red button — for destructive or recording actions."""
    return ctk.CTkButton(
        parent, text=text, command=command, width=width,
        height=40, corner_radius=20,
        font=ctk.CTkFont(family=FONT, size=13, weight="bold"),
        fg_color="#D93025", hover_color="#B3261E", text_color="#FFFFFF",
        **kwargs,
    )


def option_menu(parent, variable, values, command=None, width=175, **kwargs) -> ctk.CTkOptionMenu:
    """Themed dropdown — the same styling repeated 3× in the original app.py."""
    return ctk.CTkOptionMenu(
        parent, variable=variable, values=values, command=command,
        width=width, height=36, corner_radius=10,
        font=ctk.CTkFont(family=FONT, size=13),
        fg_color=INPUT_BG, button_color=BORDER, button_hover_color=BLUE_SURFACE,
        text_color=TEXT_PRIMARY, dropdown_fg_color=SURFACE_BRIGHT,
        dropdown_text_color=TEXT_PRIMARY, dropdown_hover_color=BLUE_SURFACE,
        **kwargs,
    )


def text_entry(parent, textvariable=None, placeholder="", **kwargs) -> ctk.CTkEntry:
    """Themed text input."""
    return ctk.CTkEntry(
        parent, textvariable=textvariable, height=36,
        corner_radius=10, border_color=BORDER, border_width=1,
        fg_color=INPUT_BG, text_color=TEXT_PRIMARY,
        font=ctk.CTkFont(family=FONT, size=13),
        placeholder_text=placeholder, **kwargs,
    )


def dialog_chrome(toplevel: ctk.CTkToplevel, title: str) -> ctk.CTkFrame:
    """Configure a CTkToplevel with project background + a header row.

    Returns the header frame so the caller can pack additional widgets
    (e.g. a count label on the right). The dialog itself gets ``fg_color``
    set, ``transient(parent)``, and ``grab_set()``.
    """
    toplevel.title(title)
    toplevel.configure(fg_color=BG)
    parent = toplevel.master
    if parent is not None:
        toplevel.transient(parent)
    toplevel.grab_set()

    header = ctk.CTkFrame(toplevel, fg_color=SURFACE, corner_radius=0, height=48)
    ctk.CTkLabel(
        header, text=title,
        font=ctk.CTkFont(family=FONT, size=16, weight="bold"),
        text_color=TEXT_PRIMARY,
    ).grid(row=0, column=0, padx=20, pady=12, sticky="w")
    header.grid_columnconfigure(0, weight=1)
    return header
