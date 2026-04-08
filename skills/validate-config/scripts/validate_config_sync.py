#!/usr/bin/env python3
import sys
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parents[3] / "lib"
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

from codex_config.commands.validate_config import *  # noqa: F401,F403


if __name__ == "__main__":
    raise SystemExit(main())
