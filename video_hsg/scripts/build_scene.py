"""把一个场景的单帧 HSGG 建成 Track / Clip / VideoGraph。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from video_hsg.config import load_config
from video_hsg.pipeline import build_scene


def main():
    parser = argparse.ArgumentParser(description="构建层次化视频场景图")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--scene", type=Path, default=None, help="含 frame_scene_graphs 的场景目录")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--no-ablation", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.scene:
        config["paths"]["scene_dir"] = str(args.scene.resolve())
    if args.out:
        config["paths"]["output_dir"] = str(args.out.resolve())
    build_scene(config, max_frames=args.max_frames, ablation=not args.no_ablation, write=True)


if __name__ == "__main__":
    main()
