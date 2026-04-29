"""Extract Tasks dialog — Phase 6.1 minimal version.

Layout (~640×520):
    [Модель ▾] [Команда ▾] [↻]   [Извлечь]    ← header row
    ─────────────────────────────────────────
    Стоимость ≈ $0.09                          ← cost hint (above textbox)
    ✓ Извлечено 12 задач (3 поля скорректированы)
    ┌─────────────────────────────────────────┐
    │ {                                        │
    │   "tasks": [...]                        │   ← raw JSON, read-only
    │ }                                        │
    └─────────────────────────────────────────┘
    Сохранено: history/.../tasks_raw.json    [Закрыть]

Phase 6.2 will replace the JSON textbox with a master-detail editor;
this dialog deliberately keeps the JSON view minimal so the swap is
isolated.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta
from tkinter import messagebox
from typing import Optional

import customtkinter as ctk

from theme import (
    BG, BORDER, FONT, GREEN, INPUT_BG, RED, SURFACE,
    TEXT_PRIMARY, TEXT_SECONDARY,
)
from ui.widgets import label, option_menu, primary_button, tonal_button
from utils import save_config


# Same curated list as Settings → OpenRouter section, kept in sync manually.
# (Phase 6.4 may replace both with a live /models browser.)
_CURATED_MODELS = [
    "anthropic/claude-sonnet-4.5",
    "anthropic/claude-haiku-4.5",
    "openai/gpt-4o",
    "google/gemini-2.5-pro",
    "deepseek/deepseek-v3",
]

_TEAMS_CACHE_KEY = "linear_teams_cache"
_TEAMS_CACHE_TTL = timedelta(hours=24)
_RECENT_MODELS_KEY = "tasks_recent_models"
_RECENT_MODELS_LIMIT = 5

# Sonnet-4.5 input price per 1M tokens. Used for the cost-estimate hint.
# Imprecise (we don't know the actual model's price) but useful as a sanity-check.
_COST_PER_1M_INPUT_TOKENS_USD = 3.0


class ExtractTasksDialog(ctk.CTkToplevel):
    """Phase-6.1 dialog. Master-detail editor lands in Phase 6.2."""

    def __init__(
        self,
        parent,
        *,
        transcript: str,
        history_folder: str,
        transcript_lang: Optional[str],
        config: dict,
    ):
        super().__init__(parent)
        self._parent = parent
        self._transcript = transcript
        self._history_folder = history_folder
        self._transcript_lang = transcript_lang
        self._config = config

        # Worker-thread plumbing: cancel_event flips on close;
        # active_client is the in-flight client we close to interrupt sockets.
        self._cancel_event = threading.Event()
        self._active_clients: list = []   # OpenRouter + Linear clients in flight
        self._teams: list[dict] = []      # populated by bootstrap

        self.title("Извлечение задач")
        self.geometry("640x520")
        self.configure(fg_color=BG)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.grab_set()

        self._build_ui()
        self._load_teams_async()

    # ── UI construction ──────────────────────────────────────────

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)   # textbox row stretches

        # --- Header row: model + team + refresh + extract ---
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=16, pady=(14, 6), sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        header.grid_columnconfigure(3, weight=1)

        label(header, "Модель").grid(row=0, column=0, padx=(0, 6), sticky="w")
        default_model = self._config.get(
            "tasks_default_model", _CURATED_MODELS[0],
        )
        recent = self._config.get(_RECENT_MODELS_KEY, []) or []
        all_models = list(_CURATED_MODELS)
        for slug in recent:
            if slug not in all_models:
                all_models.append(slug)
        self._model_var = ctk.StringVar(value=default_model)
        # CTkComboBox lets the user type custom slugs that aren't in the list.
        self._model_combo = ctk.CTkComboBox(
            header, variable=self._model_var, values=all_models,
            width=280, height=32,
            font=ctk.CTkFont(family=FONT, size=12),
            border_color=BORDER, button_color=BORDER,
            fg_color=INPUT_BG, text_color=TEXT_PRIMARY,
        )
        self._model_combo.grid(row=0, column=1, padx=(0, 12), sticky="ew")

        label(header, "Команда").grid(row=0, column=2, padx=(0, 6), sticky="w")
        self._team_var = ctk.StringVar(value="(загрузка...)")
        self._team_menu = ctk.CTkComboBox(
            header, variable=self._team_var, values=["(загрузка...)"],
            width=200, height=32, state="readonly",
            font=ctk.CTkFont(family=FONT, size=12),
            border_color=BORDER, button_color=BORDER,
            fg_color=INPUT_BG, text_color=TEXT_PRIMARY,
        )
        self._team_menu.grid(row=0, column=3, padx=(0, 4), sticky="ew")

        self._btn_refresh = tonal_button(
            header, text="↻", command=self._refresh_teams, width=36,
        )
        self._btn_refresh.grid(row=0, column=4, padx=(0, 8))

        self._btn_extract = primary_button(
            header, text="Извлечь", command=self._on_extract, width=120,
        )
        self._btn_extract.grid(row=0, column=5)

        # --- Status / cost hint row ---
        self._status_label = label(self, "", anchor="w")
        self._status_label.grid(row=1, column=0, padx=18, pady=(2, 4), sticky="ew")
        self._update_cost_hint()

        # --- JSON textbox (read-only after extract) ---
        self._json_box = ctk.CTkTextbox(
            self, wrap="word", corner_radius=10,
            fg_color=SURFACE, text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(family="Consolas", size=12),
        )
        self._json_box.grid(row=2, column=0, padx=16, pady=(2, 4), sticky="nsew")
        self._json_box.configure(state="disabled")  # nothing to show yet

        # --- Footer: saved-path + close ---
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, padx=16, pady=(2, 14), sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        self._saved_label = label(footer, "", anchor="w")
        self._saved_label.grid(row=0, column=0, sticky="ew")
        tonal_button(
            footer, text="Закрыть", command=self._on_close, width=110,
        ).grid(row=0, column=1, sticky="e")

    def _update_cost_hint(self) -> None:
        """Heuristic: ~chars/4 input tokens × Sonnet pricing × 1.3 (output)."""
        chars = len(self._transcript or "")
        approx_tokens = max(chars // 4, 1)
        cost = approx_tokens / 1_000_000 * _COST_PER_1M_INPUT_TOKENS_USD * 1.3
        self._status_label.configure(
            text=f"Стоимость ≈ ${cost:.2f} (≈ {approx_tokens:,} токенов)",
            text_color=TEXT_SECONDARY,
        )

    # ── Team bootstrap (cached 24h) ──────────────────────────────

    def _load_teams_async(self) -> None:
        """Use cache if fresh; else fetch from Linear in a worker."""
        cache = self._config.get(_TEAMS_CACHE_KEY) or {}
        fetched_at = cache.get("fetched_at")
        if fetched_at:
            try:
                age = datetime.now() - datetime.fromisoformat(fetched_at)
            except ValueError:
                age = _TEAMS_CACHE_TTL + timedelta(seconds=1)
            if age <= _TEAMS_CACHE_TTL and cache.get("data"):
                self._teams = list(cache["data"])
                self._populate_team_dropdown()
                return

        self._fetch_teams_in_worker()

    def _refresh_teams(self) -> None:
        """[↻] forces a fetch regardless of cache age."""
        self._team_var.set("(обновление...)")
        self._team_menu.configure(values=["(обновление...)"])
        self._fetch_teams_in_worker()

    def _fetch_teams_in_worker(self) -> None:
        api_key = (self._config.get("linear_api_key") or "").strip()
        if not api_key:
            self._team_var.set("(нет ключа Linear)")
            return

        def worker():
            try:
                from tasks.linear_client import LinearClient, LinearError
                client = LinearClient(api_key)
                self._active_clients.append(client)
                try:
                    result = client.bootstrap()
                finally:
                    self._active_clients.remove(client)
                    client.close()
            except Exception as e:
                if self._cancel_event.is_set():
                    return  # dialog already closing; ignore
                self.after(0, self._on_teams_error, str(e))
                return

            if self._cancel_event.is_set():
                return
            teams = result.get("teams", [])
            self._config[_TEAMS_CACHE_KEY] = {
                "data": teams,
                "fetched_at": datetime.now().isoformat(timespec="seconds"),
            }
            save_config(self._config)
            self.after(0, self._on_teams_loaded, teams)

        threading.Thread(target=worker, daemon=True).start()

    def _on_teams_loaded(self, teams: list[dict]) -> None:
        self._teams = teams
        self._populate_team_dropdown()

    def _on_teams_error(self, msg: str) -> None:
        self._team_var.set("(ошибка)")
        self._team_menu.configure(values=["(ошибка)"])
        self._status_label.configure(text=f"✗ {msg}", text_color=RED)

    def _populate_team_dropdown(self) -> None:
        if not self._teams:
            self._team_var.set("(нет команд)")
            self._team_menu.configure(values=["(нет команд)"])
            return
        labels = [f"{t['name']} ({t['key']})" for t in self._teams]
        self._team_menu.configure(values=labels)
        self._team_var.set(labels[0])

    # ── Извлечение ───────────────────────────────────────────────

    def _on_extract(self) -> None:
        team = self._selected_team()
        if not team:
            messagebox.showwarning(
                "Нет команды",
                "Выберите команду или нажмите [↻] для загрузки списка.",
            )
            return

        model = self._model_var.get().strip()
        if not model:
            messagebox.showwarning("Нет модели", "Введите slug модели OpenRouter.")
            return

        self._set_busy(True)
        self._status_label.configure(
            text="Запрос к Linear (team_context)...", text_color=TEXT_SECONDARY,
        )
        self._json_box.configure(state="normal")
        self._json_box.delete("1.0", "end")
        self._json_box.configure(state="disabled")
        self._saved_label.configure(text="")

        threading.Thread(
            target=self._run_extraction,
            args=(team, model),
            daemon=True,
        ).start()

    def _selected_team(self) -> Optional[dict]:
        label_value = self._team_var.get()
        for t in self._teams:
            if f"{t['name']} ({t['key']})" == label_value:
                return t
        return None

    def _run_extraction(self, team: dict, model: str) -> None:
        from tasks.extractor import extract, ExtractionError
        from tasks.linear_client import LinearClient, LinearError
        from tasks.openrouter_client import OpenRouterClient, OpenRouterError
        from tasks.persistence import save_tasks_raw

        linear = openrouter = None
        try:
            linear     = LinearClient(self._config["linear_api_key"])
            openrouter = OpenRouterClient(self._config["openrouter_api_key"])
            self._active_clients.extend([linear, openrouter])

            if self._cancel_event.is_set():
                return

            self.after(0, self._status_label.configure, {
                "text": f"Запрос к OpenRouter ({model})...",
                "text_color": TEXT_SECONDARY,
            })

            result = extract(
                transcript=self._transcript,
                team_id=team["id"],
                model=model,
                lang=self._transcript_lang,
                linear_client=linear,
                openrouter_client=openrouter,
            )

            if self._cancel_event.is_set():
                return

            meta = {
                "extracted_at": datetime.now().isoformat(timespec="seconds"),
                "model": result["model"],
                "team_id": team["id"],
                "team_name": team["name"],
                "transcript_lang": self._transcript_lang or "auto",
            }
            save_tasks_raw(self._history_folder, result["tasks"], meta)

            self._remember_recent_model(model)

            self.after(0, self._on_extract_success, result, meta)

        except ExtractionError as e:
            # ExtractionError carries `raw_response` when extract() got a
            # successful network round-trip but the payload was unusable.
            if not self._cancel_event.is_set():
                self.after(
                    0, self._on_extract_error, str(e), e.raw_response,
                )
        except (OpenRouterError, LinearError) as e:
            if not self._cancel_event.is_set():
                self.after(0, self._on_extract_error, str(e), None)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("extract failed")
            if not self._cancel_event.is_set():
                self.after(0, self._on_extract_error, f"{type(e).__name__}: {e}", None)
        finally:
            for c in (linear, openrouter):
                if c is not None:
                    try:
                        c.close()
                    except Exception:
                        pass
                    if c in self._active_clients:
                        self._active_clients.remove(c)
            self.after(0, self._set_busy, False)

    # ── UI updates marshalled from worker thread ─────────────────

    def _on_extract_success(self, result: dict, meta: dict) -> None:
        n = len(result["tasks"])
        corr = result["corrections"]
        if corr:
            self._status_label.configure(
                text=f"✓ Извлечено {n} задач ({corr} полей скорректированы)",
                text_color=GREEN,
            )
        else:
            self._status_label.configure(
                text=f"✓ Извлечено {n} задач",
                text_color=GREEN,
            )

        # Show what's actually on disk — guarantees "shown == saved".
        from pathlib import Path
        from tasks.persistence import RAW_FILENAME
        try:
            raw_path = Path(self._history_folder) / RAW_FILENAME
            content = raw_path.read_text(encoding="utf-8")
        except OSError:
            # Fallback: serialize the in-memory result if the file vanished.
            content = json.dumps(
                {**meta, "tasks": [t.to_dict() for t in result["tasks"]]},
                ensure_ascii=False, indent=2,
            )

        self._json_box.configure(state="normal")
        self._json_box.delete("1.0", "end")
        self._json_box.insert("1.0", content)
        self._json_box.configure(state="disabled")

        rel = os.path.relpath(
            os.path.join(self._history_folder, "tasks_raw.json"),
        )
        self._saved_label.configure(
            text=f"Сохранено: {rel}", text_color=TEXT_SECONDARY,
        )

    def _on_extract_error(self, msg: str, raw_response: Optional[str]) -> None:
        self._status_label.configure(text=f"✗ {msg}", text_color=RED)
        if raw_response:
            self._json_box.configure(state="normal")
            self._json_box.delete("1.0", "end")
            self._json_box.insert("1.0", raw_response)
            self._json_box.configure(state="disabled")

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self._btn_extract.configure(state=state)
        self._btn_refresh.configure(state=state)

    def _remember_recent_model(self, slug: str) -> None:
        """If `slug` is custom (not in curated list), prepend to FIFO-5 list."""
        if slug in _CURATED_MODELS:
            return
        recent = list(self._config.get(_RECENT_MODELS_KEY, []) or [])
        if slug in recent:
            recent.remove(slug)
        recent.insert(0, slug)
        recent = recent[:_RECENT_MODELS_LIMIT]
        self._config[_RECENT_MODELS_KEY] = recent
        save_config(self._config)

    def _on_close(self) -> None:
        """Cancel any in-flight worker, release the grab, destroy the toplevel."""
        self._cancel_event.set()
        # Closing the requests.Session sockets interrupts any blocked .post()
        # in the worker; it raises ConnectionError, which the worker catches
        # and exits silently because cancel_event is set.
        for c in list(self._active_clients):
            try:
                c.close()
            except Exception:
                pass
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
