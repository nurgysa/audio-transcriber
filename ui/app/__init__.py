"""Main App window — file selection, recording, transcription orchestration."""

from __future__ import annotations

import threading
import tkinter as tk
from typing import TYPE_CHECKING

import customtkinter as ctk

from logging_setup import init_logging
from recorder import Recorder
from theme import BG
from utils import get_app_icon_path, load_config, save_config

# Submodule re-exports. ``main`` lives in ``.main_entry`` so the repo-root
# ``app.py`` (the faulthandler bootstrap) keeps working through its existing
# ``from ui.app import main``. ``main_entry`` imports ``App`` lazily inside
# ``main()``, so this top-level import is safe — no circular load.
from .builder import build_ui
from .constants import (
    APPEARANCE_MODES,
    DEVICES,
    LANGUAGES,
    MODELS,
    SPEAKER_COUNTS,
)
from .dialogs_mixin import DialogsMixin
from .main_entry import main as main
from .recorder_mixin import RecorderMixin
from .save_mixin import SaveMixin
from .settings_mixin import SettingsMixin
from .transcription_mixin import TranscriptionMixin

# Type-only imports — these classes are referenced as type annotations on
# ``App`` attributes (``self._settings_dialog: SettingsDialog | None``, etc.)
# but constructed inside the corresponding mixins. ``from __future__ import
# annotations`` keeps the annotations as strings at runtime, so the imports
# don't need to load unless a type checker is running.
if TYPE_CHECKING:
    from audio_cutter import AudioCutter
    from transcriber import Transcriber
    from ui.dialogs.settings import SettingsDialog
    from ui.dialogs.system_monitor import SystemMonitorDialog

init_logging()

__all__ = [
    "APPEARANCE_MODES",
    "App",
    "DEVICES",
    "LANGUAGES",
    "MODELS",
    "SPEAKER_COUNTS",
    "main",
]


class App(
    DialogsMixin,
    RecorderMixin,
    SaveMixin,
    SettingsMixin,
    TranscriptionMixin,
    ctk.CTk,
):
    def __init__(self):
        super().__init__()

        self.title("Audio Transcriber")
        # Geometry will be overwritten by the fullscreen setup below — kept
        # only as the un-fullscreen fallback if the user hits Esc/F11 then
        # the window manager needs a reasonable default size to revert to.
        self.geometry("1280x800")
        self.minsize(960, 680)
        # Set the window title-bar icon. CustomTkinter sets its own default
        # icon during super().__init__() so we must call iconbitmap AFTER.
        # The .exe-embedded icon (Explorer/Taskbar) is set separately via
        # audio_transcriber.spec EXE(icon=...). Silently skip if the .ico
        # file is absent — dev runs without `python scripts/gen_icon.py`
        # shouldn't crash startup.
        _icon_path = get_app_icon_path()
        if _icon_path:
            try:
                self.iconbitmap(_icon_path)
            except tk.TclError:
                # iconbitmap can fail on some WSL/Linux/Wine setups even
                # when the file exists — fall back silently rather than
                # blocking app startup over a cosmetic icon.
                pass

        # Kiosk-style fullscreen on launch (user request 2026-05-28).
        #
        # Why brute-force geometry+overrideredirect instead of attributes(
        # '-fullscreen', True): both state('zoomed') and attributes(
        # '-fullscreen') were verified live on the maintainer's Windows 10
        # dev machine to silently NOT take effect — likely a CustomTkinter
        # init-order race that overrides our calls. Direct geometry assign
        # + overrideredirect deterministically wins because we tell Tk
        # exactly what pixels to fill.
        #
        # Approach:
        #   1. Read screen dimensions via winfo_screen*()
        #   2. Set geometry to {screen_w}x{screen_h}+0+0 (cover everything)
        #   3. overrideredirect(True) — strip OS window chrome (no title bar,
        #      no taskbar entry, no Alt-Tab thumbnail). Combined with the
        #      Extract dialog's same treatment (commit 762e96a), the entire
        #      app feels like one unified inline workspace.
        #   4. Esc binding restores normal window (overrideredirect off +
        #      smaller geometry) so user isn't trapped.
        #
        # Trade-offs (intentional for kiosk UX):
        #   - No title bar = no X button
        #   - No taskbar entry on Windows (Alt+Tab keyboard still works)
        #   - The 1280x800 geometry above is the un-fullscreen fallback
        try:
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
            self.geometry(f"{screen_w}x{screen_h}+0+0")
            self.overrideredirect(True)
        except tk.TclError:
            # Some exotic WMs reject overrideredirect — fall back to a
            # regular maximized window via state('zoomed').
            try:
                self.state("zoomed")
            except tk.TclError:
                pass

        def _exit_fullscreen(_event=None) -> None:
            """Restore normal window: re-enable WM chrome + medium geometry."""
            try:
                self.overrideredirect(False)
                self.geometry("1280x800")
            except tk.TclError:
                pass

        def _toggle_fullscreen(_event=None) -> None:
            try:
                currently_borderless = bool(self.overrideredirect())
            except tk.TclError:
                currently_borderless = False
            if currently_borderless:
                _exit_fullscreen()
            else:
                try:
                    self.geometry(
                        f"{self.winfo_screenwidth()}x"
                        f"{self.winfo_screenheight()}+0+0"
                    )
                    self.overrideredirect(True)
                except tk.TclError:
                    pass

        # Esc → exit fullscreen, F11 → toggle. Standard kiosk UX so the
        # user can grab API keys from browser etc. without being trapped.
        self.bind("<Escape>", _exit_fullscreen)
        self.bind("<F11>", _toggle_fullscreen)
        # Apply the saved appearance mode BEFORE constructing widgets so
        # tuple colors in theme.py resolve to the right palette on first
        # paint. Default "system" follows the OS setting. Persisted via
        # _on_appearance_changed when the user switches in Settings.
        saved_appearance = load_config().get("appearance_mode", "Тёмная")
        ctk.set_appearance_mode(
            APPEARANCE_MODES.get(saved_appearance, "dark"),
        )
        self.configure(fg_color=BG)

        self._audio_path: str | None = None
        self._transcriber: Transcriber | None = None
        self._recorder = Recorder()
        self._is_running = False
        self._rec_timer_id: str | None = None
        self._config = load_config()
        # One-time migration: collapse the old single ``cloud_api_key``
        # string into a per-provider dict. Lets the user keep separate
        # keys for AssemblyAI/Deepgram/Gladia/etc. without re-entering
        # one when switching the dropdown. Old field is dropped.
        if "cloud_api_keys" not in self._config:
            legacy = self._config.pop("cloud_api_key", "")
            current = self._config.get("cloud_provider", "AssemblyAI")
            self._config["cloud_api_keys"] = (
                {current: legacy} if legacy else {}
            )
            save_config(self._config)
        self._cloud_api_keys: dict[str, str] = (
            self._config["cloud_api_keys"]
        )
        # Open Settings dialog reference (singleton). Lets terms/voices saves
        # refresh its summaries live; None when dialog is closed.
        self._settings_dialog: SettingsDialog | None = None
        # Open System Monitor dialog reference (singleton). Non-modal —
        # designed to stay open during transcription. Re-clicking the
        # button just brings the existing window to the front.
        self._monitor_dialog: SystemMonitorDialog | None = None
        # Most recently opened AudioCutter instance. Tracked only so that
        # _on_appearance_changed can ping it to redraw its Canvas — the
        # cutter is otherwise free to be reopened/recreated freely.
        self._cutter: AudioCutter | None = None
        # Cancel signal for the worker thread. Worker checks this between
        # segments and around the diarization subprocess; setting it
        # interrupts the run within ~250 ms.
        self._cancel_event = threading.Event()
        # Path to the most recent successful transcription's history folder.
        # Populated in _on_complete; consumed by _open_extract_tasks_dialog.
        self._last_history_folder: str | None = None

        # First-run detection — builder.py uses this to conditionally render
        # the yellow banner at row=0 prompting the user to enter API keys.
        # Triggers when the AssemblyAI key is empty after config load.
        # AssemblyAI is the MVP default + only provider that delivers a
        # diarized transcript out of the box; without its key the app
        # can't do its primary job.
        self._first_run = not self._cloud_api_keys.get("AssemblyAI", "").strip()

        build_ui(self)



