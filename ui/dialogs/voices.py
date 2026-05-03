"""Speaker enrollment dialog — record/import a sample, name the speaker."""

from __future__ import annotations

import os
import sys
import threading
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk

from recorder import Recorder
from theme import (
    BG,
    BLUE,
    BLUE_DIM,
    BORDER,
    FONT,
    RED,
    SURFACE,
    SURFACE_BRIGHT,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)
from utils import save_config

# voices.py lives at ui/dialogs/voices.py — go up three levels for project root.
# Used to locate enrollment_worker.py at runtime regardless of which CWD the
# app is launched from.
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


class VoicesDialog(ctk.CTkToplevel):
    """Dialog for managing enrolled voices (CRUD)."""

    def __init__(self, parent, config: dict, hf_token: str | None, on_save):
        super().__init__(parent)
        self.title("Голоса")
        self.geometry("520x560")
        self.configure(fg_color=BG)
        self.transient(parent)
        self.grab_set()

        self._config = config
        self._hf_token = hf_token
        self._on_save = on_save
        self._enrolling = False  # guards against re-entry while worker runs
        # Recording state (separate Recorder instance — must not share with
        # the main window's recorder, which the user may have running).
        self._voice_recorder: Recorder | None = None
        self._rec_tmp_dir: str | None = None
        self._rec_tick_job: str | None = None  # after() handle

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # --- Header ---
        header = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=48)
        header.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(
            header, text="Голоса — библиотека спикеров",
            font=ctk.CTkFont(family=FONT, size=16, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=20, pady=12)

        # --- Add card ---
        add_card = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=12)
        add_card.grid(row=1, column=0, padx=16, pady=(12, 8), sticky="ew")
        add_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            add_card,
            text="Добавьте аудио-образец (10–30 с, один говорящий) и укажите имя.\n"
                 "Во время диаризации голос будет автоматически распознан по имени.",
            font=ctk.CTkFont(family=FONT, size=12),
            text_color=TEXT_SECONDARY, justify="left", anchor="w",
        ).grid(row=0, column=0, columnspan=2, padx=12, pady=(12, 6), sticky="ew")

        # Two buttons: record in-app OR import an existing file. Each
        # produces a WAV path that feeds the same enrollment pipeline.
        btn_row = ctk.CTkFrame(add_card, fg_color="transparent")
        btn_row.grid(row=1, column=0, columnspan=2, padx=12, pady=(4, 12), sticky="ew")
        btn_row.grid_columnconfigure(2, weight=1)

        self._record_btn = ctk.CTkButton(
            btn_row, text="⏺  Записать", height=36, corner_radius=18,
            font=ctk.CTkFont(family=FONT, size=13, weight="bold"),
            fg_color="#D93025", hover_color="#B3261E", text_color="#FFFFFF",
            command=self._toggle_record,
        )
        self._record_btn.grid(row=0, column=0, padx=(0, 8))

        self._enroll_btn = ctk.CTkButton(
            btn_row, text="Загрузить из файла", height=36, corner_radius=18,
            font=ctk.CTkFont(family=FONT, size=13, weight="bold"),
            fg_color=BLUE, hover_color=BLUE_DIM, text_color="#FFFFFF",
            command=self._start_enroll_from_file,
        )
        self._enroll_btn.grid(row=0, column=1, padx=(0, 8))

        self._status_lbl = ctk.CTkLabel(
            btn_row, text="", font=ctk.CTkFont(family=FONT, size=12),
            text_color=TEXT_SECONDARY, anchor="w",
        )
        self._status_lbl.grid(row=0, column=2, padx=(8, 0), sticky="ew")

        # --- List ---
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

        from voice_library import voices_from_config
        voices = voices_from_config(self._config)

        if not voices:
            ctk.CTkLabel(
                self._list_frame_outer,
                text="Нет сохранённых голосов. Добавьте образцы выше.",
                font=ctk.CTkFont(family=FONT, size=13),
                text_color=TEXT_SECONDARY,
            ).grid(row=0, column=0, pady=20)
            return

        for i, voice in enumerate(voices):
            row = ctk.CTkFrame(
                self._list_frame_outer, fg_color=SURFACE_BRIGHT,
                corner_radius=10, height=44,
            )
            row.grid(row=i, column=0, padx=4, pady=3, sticky="ew")
            row.grid_columnconfigure(0, weight=1)

            created = voice.get("created_at") or ""
            subtitle = f"dim={voice['dim']}" + (f" · {created[:10]}" if created else "")

            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.grid(row=0, column=0, padx=12, pady=4, sticky="ew")
            inner.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                inner, text=voice["name"], anchor="w",
                font=ctk.CTkFont(family=FONT, size=13, weight="bold"),
                text_color=TEXT_PRIMARY,
            ).grid(row=0, column=0, sticky="w")
            ctk.CTkLabel(
                inner, text=subtitle, anchor="w",
                font=ctk.CTkFont(family=FONT, size=11),
                text_color=TEXT_SECONDARY,
            ).grid(row=1, column=0, sticky="w")

            ctk.CTkButton(
                row, text="✕", width=32, height=32, corner_radius=16,
                font=ctk.CTkFont(family=FONT, size=14),
                fg_color="transparent", hover_color=BORDER,
                text_color=RED,
                command=lambda n=voice["name"]: self._delete_voice(n),
            ).grid(row=0, column=1, padx=(0, 8), pady=4)

    def _update_count(self):
        from voice_library import voice_names
        self._lbl_count.configure(text=f"Голосов: {len(voice_names(self._config))}")

    def _delete_voice(self, name: str):
        from voice_library import remove_voice_from_config
        if remove_voice_from_config(self._config, name):
            save_config(self._config)
            self._on_save()
            self._render_list()
            self._update_count()

    def _start_enroll_from_file(self):
        if self._enrolling:
            return
        if not self._hf_token:
            messagebox.showwarning(
                "HF Token требуется",
                "Для извлечения эмбеддинга голоса нужен Hugging Face token.\n\n"
                "Введите токен в главном окне (галочка «Диаризация» → поле HF Token), "
                "сохраните настройки и откройте этот диалог заново.",
            )
            return

        path = filedialog.askopenfilename(
            title="Выберите аудио-образец голоса (10–30 с)",
            filetypes=[("Audio files", "*.mp3 *.wav *.m4a"), ("All files", "*.*")],
        )
        if not path:
            return

        name = simpledialog.askstring(
            "Имя спикера", "Как зовут этого спикера?", parent=self,
        )
        if not name or not name.strip():
            return
        name = name.strip()

        self._set_enrolling(True, f"Анализ голоса «{name}»...")
        thread = threading.Thread(
            target=self._run_enrollment, args=(path, name), daemon=True,
        )
        thread.start()

    def _set_enrolling(self, enrolling: bool, status: str = ""):
        self._enrolling = enrolling
        disabled = "disabled" if enrolling else "normal"
        self._enroll_btn.configure(state=disabled)
        # Recording and enrollment are mutually exclusive. The record button
        # is only re-enabled after enrollment finishes; during enrollment,
        # starting a recording would make the UI ambiguous.
        self._record_btn.configure(state=disabled)
        self._status_lbl.configure(
            text=status,
            text_color=BLUE if enrolling else TEXT_SECONDARY,
        )

    # ── In-app recording ────────────────────────────────────────

    def _toggle_record(self):
        """Start/stop recording. Same button acts as Record and Stop."""
        if self._enrolling:
            return
        if self._voice_recorder is None or not self._voice_recorder.is_recording:
            self._start_recording()
        else:
            self._stop_recording_and_enroll()

    def _start_recording(self):
        # Route recordings through a throwaway temp dir so they don't
        # pollute Documents. Recorder auto-names the file as
        # recording_<timestamp>.wav inside the given dir.
        import tempfile
        self._rec_tmp_dir = tempfile.mkdtemp(prefix="voice_enroll_")
        self._voice_recorder = Recorder(output_dir=self._rec_tmp_dir)
        try:
            self._voice_recorder.start()
        except Exception as e:
            messagebox.showerror(
                "Микрофон недоступен", f"Не удалось запустить запись:\n\n{e}",
            )
            self._cleanup_recording(delete_file=True)
            return

        self._record_btn.configure(text="⏹  Стоп", fg_color="#B3261E")
        self._enroll_btn.configure(state="disabled")
        self._status_lbl.configure(
            text="00:00 — говорите 10–30 секунд", text_color="#D93025",
        )
        self._tick_timer()

    def _tick_timer(self):
        """Update elapsed-time label every 500 ms while recording."""
        if self._voice_recorder is None or not self._voice_recorder.is_recording:
            return
        elapsed = int(self._voice_recorder.elapsed)
        m, s = divmod(elapsed, 60)
        self._status_lbl.configure(text=f"{m:02d}:{s:02d} — говорите 10–30 секунд")
        self._rec_tick_job = self.after(500, self._tick_timer)

    def _stop_recording_and_enroll(self):
        if self._rec_tick_job is not None:
            try:
                self.after_cancel(self._rec_tick_job)
            except Exception:
                pass
            self._rec_tick_job = None

        recorder = self._voice_recorder
        if recorder is None:
            return
        # Capture elapsed BEFORE stop(): Recorder.elapsed returns 0.0 once
        # _is_recording flips to False, so reading it after stop() would
        # underreport every recording as zero seconds.
        elapsed = recorder.elapsed
        try:
            wav_path = recorder.stop()
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось остановить запись:\n\n{e}")
            self._cleanup_recording(delete_file=True)
            return

        self._record_btn.configure(text="⏺  Записать", fg_color="#D93025")
        self._enroll_btn.configure(state="normal")

        if not wav_path or not os.path.isfile(wav_path):
            self._status_lbl.configure(text="Запись не сохранена", text_color=RED)
            self._cleanup_recording(delete_file=True)
            return

        # Require at least 5 seconds of speech. Under 5 s the embedding is
        # noisy enough that matching accuracy drops sharply — no point
        # saving it and discovering that later.
        if elapsed < 5.0:
            messagebox.showwarning(
                "Слишком коротко",
                f"Запись длится всего {elapsed:.1f} с. Нужно минимум 5 секунд "
                "непрерывной речи. Попробуйте ещё раз.",
            )
            self._status_lbl.configure(text="Запись слишком короткая", text_color=RED)
            self._cleanup_recording(delete_file=True)
            return

        name = simpledialog.askstring(
            "Имя спикера",
            f"Запись {elapsed:.1f} с сохранена. Как зовут этого спикера?",
            parent=self,
        )
        if not name or not name.strip():
            self._cleanup_recording(delete_file=True)
            self._status_lbl.configure(text="Отменено", text_color=TEXT_SECONDARY)
            return
        name = name.strip()

        # Hand off to the same enrollment worker the file-import path uses.
        self._set_enrolling(True, f"Анализ голоса «{name}»...")
        thread = threading.Thread(
            target=self._run_enrollment_and_cleanup,
            args=(wav_path, name), daemon=True,
        )
        thread.start()

    def _run_enrollment_and_cleanup(self, audio_path: str, name: str):
        """Wrapper: run enrollment, then delete the source recording."""
        try:
            self._run_enrollment(audio_path, name)
        finally:
            # Clean up the raw recording AND the temp dir. _run_enrollment
            # may have already succeeded by now — deletion is idempotent.
            self._cleanup_recording(delete_file=True)

    def _cleanup_recording(self, delete_file: bool):
        """Release recorder + remove temp dir. Safe to call repeatedly."""
        if self._voice_recorder is not None and self._voice_recorder.is_recording:
            try:
                self._voice_recorder.stop()
            except Exception:
                pass
        self._voice_recorder = None
        if delete_file and self._rec_tmp_dir and os.path.isdir(self._rec_tmp_dir):
            import shutil
            try:
                shutil.rmtree(self._rec_tmp_dir, ignore_errors=True)
            except Exception:
                pass
        self._rec_tmp_dir = None

    def _run_enrollment(self, audio_path: str, name: str):
        """Worker thread: ffmpeg normalize → enrollment subprocess → save."""
        import json as _json
        import subprocess as _subprocess
        try:
            # Pre-process the sample through ensure_wav (normalization makes
            # low-input-volume samples comparable to higher-volume ones at
            # matching time — both detection and enrollment go through the
            # same filter chain, so the signal domain is consistent).
            from audio_io import ensure_wav
            wav_path, wav_is_temp = ensure_wav(audio_path, normalize=True)

            worker = os.path.join(_PROJECT_ROOT, "enrollment_worker.py")
            env = dict(os.environ)
            if self._hf_token:
                env["HF_TOKEN"] = self._hf_token

            try:
                proc = _subprocess.run(
                    [sys.executable, worker, wav_path],
                    env=env, capture_output=True, text=True,
                    encoding="utf-8", timeout=180,
                )
            finally:
                if wav_is_temp:
                    try:
                        os.unlink(wav_path)
                    except OSError:
                        pass

            if proc.returncode != 0:
                raise RuntimeError(
                    f"enrollment_worker exit {proc.returncode}:\n"
                    f"{(proc.stderr or '')[-1500:]}"
                )

            data = _json.loads((proc.stdout or "").strip())
            import base64 as _b64

            import numpy as _np
            emb = _np.frombuffer(
                _b64.b64decode(data["embedding_b64"]), dtype=_np.float32,
            )

            from voice_library import save_voice_to_config
            save_voice_to_config(self._config, name, emb)
            save_config(self._config)

            self.after(0, self._on_enroll_success, name)
        except _subprocess.TimeoutExpired:
            self.after(0, self._on_enroll_fail,
                       "Таймаут: процесс извлечения эмбеддинга превысил 3 минуты.")
        except Exception as e:
            self.after(0, self._on_enroll_fail, str(e))

    def _on_enroll_success(self, name: str):
        self._set_enrolling(False, f"Голос «{name}» добавлен ✓")
        self._on_save()
        self._render_list()
        self._update_count()

    def _on_enroll_fail(self, message: str):
        self._set_enrolling(False, "")
        messagebox.showerror(
            "Не удалось извлечь эмбеддинг",
            f"Ошибка при анализе аудио-образца.\n\n{message[-2000:]}",
        )

    def _close(self):
        # Don't leak an active sounddevice stream if the user closes the
        # dialog mid-recording. Drop any in-progress recording and its temp
        # file — the user didn't confirm a name, so there's nothing to save.
        if self._rec_tick_job is not None:
            try:
                self.after_cancel(self._rec_tick_job)
            except Exception:
                pass
            self._rec_tick_job = None
        self._cleanup_recording(delete_file=True)
        self.grab_release()
        self.destroy()
