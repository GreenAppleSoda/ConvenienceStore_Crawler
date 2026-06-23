# 프로젝트 루트를 sys.path에 추가 (하위 폴더 크롤러에서 lib import용)
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
