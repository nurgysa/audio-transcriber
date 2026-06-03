"""argparse wiring for the CLI: subcommands, required groups, choices."""
from __future__ import annotations

import pytest

from cli.app import build_parser


def test_transcribe_parses_core_flags():
    args = build_parser().parse_args(
        ["transcribe", "a.mp3", "--provider", "AssemblyAI", "--diarize", "--json"]
    )
    assert args.command == "transcribe"
    assert args.audio == "a.mp3"
    assert args.provider == "AssemblyAI"
    assert args.diarize is True
    assert args.json is True
    assert callable(args.func)


def test_language_choice_is_validated():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["transcribe", "a.mp3", "--language", "xx"])


def test_extract_tasks_requires_a_source():
    # Neither --transcript nor --stdin → required mutually-exclusive group fails.
    with pytest.raises(SystemExit):
        build_parser().parse_args(["extract-tasks"])


def test_send_requires_backend_and_container():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["send", "--stdin"])


def test_pipeline_defaults_to_json_output():
    args = build_parser().parse_args(["pipeline", "a.mp3"])
    assert args.json is True


def test_no_subcommand_leaves_func_unset():
    args = build_parser().parse_args([])
    assert getattr(args, "func", None) is None
