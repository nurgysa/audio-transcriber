"""SettingsDialog has a reactive banner subscribed to the three required vars.

Source/AST checks only — see feedback_ui_app_import_breaks_linux_ci.
"""
from __future__ import annotations

import ast
from pathlib import Path

SETTINGS_PATH = (
    Path(__file__).resolve().parent.parent / "ui" / "dialogs" / "settings.py"
)


def _get_method_source(class_name: str, method_name: str) -> str | None:
    source = SETTINGS_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef) and cls.name == class_name:
            for fn in cls.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == method_name:
                    return ast.unparse(fn)
    return None


def test_init_subscribes_trace_on_three_vars():
    init_src = _get_method_source("SettingsDialog", "__init__")
    assert init_src is not None

    for var_name in ("_cloud_api_key_var", "_lang_var", "_cloud_provider_var"):
        assert var_name in init_src, (
            f"__init__ must subscribe trace_add on {var_name}"
        )
    assert init_src.count("trace_add") >= 3, (
        f"Expected ≥ 3 trace_add calls in __init__ "
        f"(got {init_src.count('trace_add')})"
    )


def test_destroy_unregisters_trace_tokens():
    """The PR #25 pattern: store trace tokens as instance attrs, remove
    in destroy() to avoid stale-trace TclError on dialog re-open."""
    destroy_src = _get_method_source("SettingsDialog", "destroy")
    assert destroy_src is not None

    assert "trace_remove" in destroy_src, (
        "destroy() must unregister trace tokens to prevent stale-trace "
        "TclError on dialog re-open (PR #25 pattern)"
    )


def test_update_banner_method_exists():
    src = _get_method_source("SettingsDialog", "_update_banner")
    assert src is not None, (
        "_update_banner method must exist (subscribed via trace_add)"
    )


def test_banner_click_handler_exists():
    """Banner is clickable per spec — at least one jump handler must exist
    that calls _tabview.set('Транскрипция')."""
    src = SETTINGS_PATH.read_text(encoding="utf-8")
    assert 'self._tabview.set("Транскрипция")' in src, (
        "Banner click handler must switch to Транскрипция tab"
    )
    assert "focus_set()" in src, (
        "Banner click handler must focus the relevant widget"
    )
