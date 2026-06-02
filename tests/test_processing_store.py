from processing.model import QueueItem, StageStatus
from processing.store import is_meeting_folder, load_active, save_active, stage_status_from_folder


def test_save_then_load_round_trips(tmp_path):
    p = tmp_path / "queue.json"
    items = [
        QueueItem(id="a", audio_path="/x.wav", title="x", created_at="t",
                  auto=True, transcript=StageStatus.DONE),
    ]
    save_active(items, path=p)
    loaded = load_active(path=p)
    assert loaded == items


def test_load_missing_file_returns_empty(tmp_path):
    assert load_active(path=tmp_path / "nope.json") == []


def test_load_malformed_returns_empty(tmp_path):
    p = tmp_path / "queue.json"
    p.write_text("{ not json", encoding="utf-8")
    assert load_active(path=p) == []


def test_save_is_atomic_no_tmp_left(tmp_path):
    p = tmp_path / "queue.json"
    save_active([], path=p)
    assert p.is_file()
    assert not (tmp_path / ".queue.json.tmp").exists()


def _touch(folder, name):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text("x", encoding="utf-8")


def test_stage_status_all_pending_empty_folder(tmp_path):
    s = stage_status_from_folder(str(tmp_path))
    assert s == {
        "transcript": StageStatus.PENDING,
        "protocol": StageStatus.PENDING,
        "tasks": StageStatus.PENDING,
    }


def test_stage_status_full_meeting(tmp_path):
    for name in ("transcript.md", "protocol.md", "tasks.json"):
        _touch(tmp_path, name)
    s = stage_status_from_folder(str(tmp_path))
    assert s["transcript"] is StageStatus.DONE
    assert s["protocol"] is StageStatus.DONE
    assert s["tasks"] is StageStatus.DONE


def test_stage_status_draft_only_is_awaiting_review(tmp_path):
    _touch(tmp_path, "transcript.md")
    _touch(tmp_path, "tasks_raw.json")
    s = stage_status_from_folder(str(tmp_path))
    assert s["tasks"] is StageStatus.AWAITING_REVIEW


def test_is_meeting_folder(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    meeting = tmp_path / "m"
    _touch(meeting, "transcript.md")
    assert is_meeting_folder(str(meeting)) is True
    assert is_meeting_folder(str(empty)) is False
