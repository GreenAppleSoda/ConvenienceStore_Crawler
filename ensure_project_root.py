# 프로젝트 루트를 sys.path에 추가 (GitHub Actions / 하위 폴더 스크립트 실행용)
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lib._bootstrap  # noqa: F401, E402
