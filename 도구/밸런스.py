#!/usr/bin/env python3
"""프로젝트 어디서나 실행 가능한 한국어 CLI 진입점."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from balance.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
