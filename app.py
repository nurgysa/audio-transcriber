"""Entry point — installs the C-level fault handler, then hands off to ui.app.

Faulthandler MUST be installed BEFORE any C-extension imports (ctranslate2,
torch, pyannote). Without it, a SIGSEGV/SIGABRT during CUDA teardown leaves
no diagnostic trail — the process just vanishes. Importing ui.app pulls in
Transcriber → ctranslate2, so we install faulthandler first and only then
import the rest.
"""

import faulthandler
import os

_LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_LOGS_DIR, exist_ok=True)
_FAULT_LOG = open(os.path.join(_LOGS_DIR, "faulthandler.log"), "w", encoding="utf-8")
faulthandler.enable(file=_FAULT_LOG, all_threads=True)

from ui.app import main  # noqa: E402  (must follow faulthandler.enable)

if __name__ == "__main__":
    main()
