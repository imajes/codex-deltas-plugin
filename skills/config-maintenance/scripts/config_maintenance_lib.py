from __future__ import annotations

import os
import sys
from pathlib import Path

CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
LIB_DIR = CODEX_HOME / "lib"
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

from codex_config.shared import *  # noqa: F401,F403
