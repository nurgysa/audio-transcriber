from tasks.backends.base import ExistingItem
from tasks.dedup import SentTask, dedup_marker, dedup_signature


def test_signature_stable_and_normalized():
    # Same title (modulo case/punct/space) → same signature.
    a = dedup_signature("Изучить систему СУП")
    b = dedup_signature("  изучить  систему,  суп ")
    assert a == b
    assert len(a) == 12


def test_signature_differs_for_different_titles():
    assert dedup_signature("Задача А") != dedup_signature("Задача Б")


def test_marker_wraps_signature():
    m = dedup_marker("Изучить систему СУП")
    assert m == f"<!-- audiotx-dedup:{dedup_signature('Изучить систему СУП')} -->"


def test_existing_item_defaults_description_empty():
    it = ExistingItem(title="t", ref="r", identifier="NUR-1", url="u")
    assert it.description == ""


def test_sent_task_accepts_description():
    s = SentTask(
        title="t", backend="linear", container_id="c", ref="r",
        identifier="NUR-1", url="u", meeting_name="", meeting_date="",
        description="d",
    )
    assert s.description == "d"
