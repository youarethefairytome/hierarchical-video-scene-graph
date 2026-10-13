"""没有预处理结果时先构建，然后打开 Gradio。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "processed" / "navqa_seq0" / "scene_bundle.json"


def main():
    if not BUNDLE.exists():
        subprocess.check_call([sys.executable, str(ROOT / "scripts" / "build_scene.py")])
    subprocess.check_call([sys.executable, str(ROOT / "app" / "gradio_app.py")])


if __name__ == "__main__":
    main()
