"""Shared CustomTkinter theme constants.

Single source of truth for colors, fonts, and UI chrome used across
app.py and audio_cutter.py. Keeping them here means changing the palette
requires editing one file instead of two.

Palette is Google Dark Material Design. If you need to add a new semantic
color, put it here, not in a dialog class.
"""

# --- Google Dark Material Design colors ---
BG = "#1F1F1F"
SURFACE = "#282828"
SURFACE_BRIGHT = "#303030"
BORDER = "#3C4043"
TEXT_PRIMARY = "#E8EAED"
TEXT_SECONDARY = "#9AA0A6"
BLUE = "#1A73E8"
BLUE_DIM = "#1557B0"
BLUE_SURFACE = "#2D3B4E"
GREEN = "#81C995"
RED = "#F28B82"
YELLOW = "#FDD663"
PROGRESS_BG = "#3C4043"
INPUT_BG = "#303030"
FONT = "Segoe UI"

# --- Waveform colors (audio_cutter only, but live here for consistency) ---
WAVE_COLOR = "#5E97D0"
WAVE_SELECTED = "#8AB4F8"
MARKER_START_COLOR = "#81C995"
MARKER_END_COLOR = "#F28B82"
SELECTION_COLOR = "#1A73E8"
