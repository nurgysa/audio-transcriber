import os

from directory.schema import Project
from processing.layout import move_into, project_dirname, target_dir


def test_project_dirname_plain_name():
    assert project_dirname(Project(name="Kitng", id="p1")) == "Kitng"


def test_project_dirname_sanitizes_illegal_chars():
    assert project_dirname(Project(name='a/b:c*d', id="p1")) == "a_b_c_d"


def test_project_dirname_falls_back_to_id_when_empty():
    p = Project(name='///', id="abcdef1234567890")
    assert project_dirname(p) == "abcdef12"


def test_target_dir_none_is_root(tmp_path):
    assert target_dir(str(tmp_path), None) == str(tmp_path)


def test_target_dir_project_is_subfolder(tmp_path):
    p = Project(name="Kitng", id="p1")
    assert target_dir(str(tmp_path), p) == os.path.join(str(tmp_path), "Kitng")


def test_move_into_moves_folder(tmp_path):
    src = tmp_path / "meeting"
    src.mkdir()
    (src / "transcript.md").write_text("x", encoding="utf-8")
    dest = tmp_path / "Kitng"
    new = move_into(str(src), str(dest))
    assert new == os.path.join(str(dest), "meeting")
    assert os.path.isfile(os.path.join(new, "transcript.md"))
    assert not src.exists()


def test_move_into_noop_when_already_there(tmp_path):
    src = tmp_path / "meeting"
    src.mkdir()
    new = move_into(str(src), str(tmp_path))
    assert new == os.path.normpath(str(src))
    assert src.exists()


def test_move_into_collision_appends_suffix(tmp_path):
    src = tmp_path / "meeting"
    src.mkdir()
    dest = tmp_path / "Kitng"
    (dest / "meeting").mkdir(parents=True)  # occupied
    new = move_into(str(src), str(dest))
    assert new == os.path.join(str(dest), "meeting-2")
    assert os.path.isdir(new)
