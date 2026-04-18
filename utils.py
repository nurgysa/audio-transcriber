import json
import os
import shutil
from datetime import datetime

SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a"}

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def validate_audio(path: str) -> bool:
    """Check that the file exists and has a supported audio extension."""
    if not os.path.isfile(path):
        return False
    ext = os.path.splitext(path)[1].lower()
    return ext in SUPPORTED_EXTENSIONS


def get_output_path(audio_path: str) -> str:
    """Return the default .txt output path next to the audio file."""
    base, _ = os.path.splitext(audio_path)
    return base + ".txt"


def save_transcript(text: str, output_path: str) -> None:
    """Write transcript text to a UTF-8 file."""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(text)


def check_ffmpeg() -> bool:
    """Return True if ffmpeg is found in PATH."""
    return shutil.which("ffmpeg") is not None


def load_config() -> dict:
    if os.path.isfile(_CONFIG_PATH):
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(config: dict) -> None:
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# ── History — each entry is a folder on disk ─────────────────

_HISTORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history")


def _ensure_history_dir() -> str:
    os.makedirs(_HISTORY_DIR, exist_ok=True)
    return _HISTORY_DIR


def create_history_entry(
    audio_file_path: str,
    transcript_text: str,
    language: str | None,
    model: str,
) -> str:
    """Create a history folder with audio copy, transcript.txt and description.md.

    Returns the path to the created folder.
    """
    _ensure_history_dir()

    audio_name = os.path.basename(audio_file_path)
    base_name = os.path.splitext(audio_name)[0]
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    folder_name = f"{timestamp}_{base_name}"
    folder_path = os.path.join(_HISTORY_DIR, folder_name)
    os.makedirs(folder_path, exist_ok=True)

    # Copy audio file
    if os.path.isfile(audio_file_path):
        shutil.copy2(audio_file_path, os.path.join(folder_path, audio_name))

    # Save transcript
    txt_path = os.path.join(folder_path, "transcript.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(transcript_text)

    # Save description.md
    lang_label = language or "auto"
    md_content = (
        f"# {audio_name}\n\n"
        f"- **Дата:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"- **Язык:** {lang_label}\n"
        f"- **Модель:** {model}\n"
        f"- **Аудио файл:** {audio_name}\n"
        f"- **Исходный путь:** {audio_file_path}\n"
    )
    md_path = os.path.join(folder_path, "description.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    return folder_path


def list_history_entries() -> list[dict]:
    """Scan the history directory and return entries sorted by date (newest first).

    Each entry dict: folder_path, folder_name, audio_file, date_created.
    """
    _ensure_history_dir()
    entries = []
    for name in os.listdir(_HISTORY_DIR):
        folder_path = os.path.join(_HISTORY_DIR, name)
        if not os.path.isdir(folder_path):
            continue

        # Find audio file (not .txt, not .md)
        audio_file = None
        has_transcript = False
        for f in os.listdir(folder_path):
            ext = os.path.splitext(f)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                audio_file = f
            elif f == "transcript.txt":
                has_transcript = True

        # Parse date from folder name (YYYY-MM-DD_HH-MM-SS_...)
        date_str = name[:19] if len(name) >= 19 else name
        date_display = date_str.replace("_", " ", 1).replace("-", ":", 3)

        entries.append({
            "folder_path": folder_path,
            "folder_name": name,
            "audio_file": audio_file,
            "has_transcript": has_transcript,
            "date_created": date_str,
            "date_display": date_display,
        })

    entries.sort(key=lambda e: e["date_created"], reverse=True)
    return entries


def delete_history_entry(folder_path: str) -> None:
    """Delete a history folder and all its contents."""
    if os.path.isdir(folder_path):
        shutil.rmtree(folder_path)


def open_in_explorer(path: str) -> None:
    """Open a folder in the system file explorer."""
    if os.path.isdir(path):
        os.startfile(path)
