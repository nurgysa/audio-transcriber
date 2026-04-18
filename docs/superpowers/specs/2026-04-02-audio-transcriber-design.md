# Audio Transcriber — Design Spec

## Context

Needed: a local Windows 10 desktop application that transcribes audio files in Kazakh, Russian, and English. Must run fully offline after initial model download. User has Python 3.10, GTX 1650 Ti (4 GB VRAM, no CUDA PyTorch), and no existing project.

## Stack

- **Engine**: faster-whisper (CTranslate2 — 4x faster than original Whisper on CPU, supports own CUDA)
- **Model**: `medium` (~1.5 GB, best balance for Kazakh quality vs. speed)
- **GUI**: CustomTkinter (modern look, minimal code)
- **Audio handling**: faster-whisper handles MP3/WAV/M4A natively via FFmpeg
- **FFmpeg**: required in PATH (user installs separately or bundled)

## Project Structure

```
C:\Users\nurgisa\Documents\audio-transcriber\
├── app.py              # GUI + entry point
├── transcriber.py      # faster-whisper wrapper
├── utils.py            # File validation, save to TXT
└── requirements.txt    # Dependencies
```

## Module Details

### app.py — GUI + Entry Point

Single-window application (~600x500 px) with CustomTkinter dark theme.

**UI Elements:**
1. File selector — button + label showing selected file path
2. Language dropdown — "Auto-detect", "Kazakh (kk)", "Russian (ru)", "English (en)"
3. "Transcribe" button — disabled until file selected, disabled during transcription
4. Progress bar — indeterminate during model load, determinate during transcription
5. Text area — scrollable, shows transcription result
6. Action buttons — "Save TXT" and "Copy to clipboard"

**Threading:**
- Transcription runs in `threading.Thread(daemon=True)` to keep GUI responsive
- Progress updates via `root.after()` from thread to main loop
- Cancel not required for v1 (model runs segment-by-segment, hard to interrupt cleanly)

### transcriber.py — Transcription Engine

```python
class Transcriber:
    def __init__(self, model_size="medium", device="auto"):
        """
        device="auto": tries cuda, falls back to cpu
        Model downloads to ~/.cache/huggingface/ on first use
        """

    def transcribe(self, audio_path, language=None, on_progress=None):
        """
        Args:
            audio_path: path to MP3/WAV/M4A file
            language: "kk", "ru", "en", or None for auto-detect
            on_progress: callback(percent: float) called per segment

        Returns:
            str: full transcription text
        """
```

**Progress calculation:** faster-whisper yields segments with timestamps. Progress = last_segment_end / audio_duration * 100.

### utils.py — Utilities

- `validate_audio(path) -> bool` — checks extension is .mp3/.wav/.m4a
- `save_transcript(text, output_path)` — writes UTF-8 text file
- `get_output_path(audio_path)` — returns audio_path with .txt extension

## Dependencies (requirements.txt)

```
faster-whisper>=1.0.0
customtkinter>=5.2.0
```

FFmpeg must be installed separately and available in PATH.

## Language Mapping

| UI Label       | Whisper code | Notes                    |
|----------------|-------------|--------------------------|
| Auto-detect    | None        | Whisper auto-detects     |
| Kazakh         | "kk"        | Supported since Whisper  |
| Russian        | "ru"        | High quality             |
| English        | "en"        | High quality             |

## Error Handling

- **No FFmpeg**: show error dialog on startup if ffmpeg not found in PATH
- **No file selected**: "Transcribe" button stays disabled
- **Invalid format**: show error dialog
- **Model download fails**: show error with retry suggestion
- **Transcription error**: show error in text area, re-enable button

## Verification

1. Install: `pip install -r requirements.txt`
2. Ensure FFmpeg in PATH: `ffmpeg -version`
3. Run: `python app.py`
4. Select an MP3/WAV/M4A file
5. Choose language (or auto)
6. Click Transcribe
7. Verify text appears, save to TXT works
