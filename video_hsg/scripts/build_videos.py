"""把已下载的 cam0 原图编成两段 mp4：无框，以及带主体识别框。"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from video_hsg.config import load_config
from video_hsg.service import DemoSession

BUNDLE = ROOT / "processed" / "navqa_seq0" / "scene_bundle.json"
OUT_DIR = ROOT / "data" / "video"
PLAIN = OUT_DIR / "navqa_seq0_plain.mp4"
BOXES = OUT_DIR / "navqa_seq0_boxes.mp4"


def ffmpeg_exe() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _jpeg(image: Image.Image) -> bytes:
    if image.width > 960:
        scale = 960 / image.width
        image = image.resize((960, int(image.height * scale)), Image.Resampling.BILINEAR)
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def encode(session: DemoSession, destination: Path, show_boxes: bool):
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg_exe(),
        "-y",
        "-f",
        "image2pipe",
        "-framerate",
        "8",
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "23",
        "-movflags",
        "+faststart",
        str(destination),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert process.stdin is not None
    try:
        for frame_id in range(session.n_frames):
            image = session.frame_view(frame_id, False, [], show_boxes=show_boxes)["frame"]
            process.stdin.write(_jpeg(image))
            if frame_id % 100 == 0:
                print(f"  {destination.name} {frame_id}/{session.n_frames}", flush=True)
    finally:
        process.stdin.close()
    error = process.stderr.read().decode("utf-8", "replace") if process.stderr else ""
    code = process.wait()
    if code != 0:
        raise RuntimeError(error[-2000:])
    print(f"wrote {destination} ({destination.stat().st_size / 1024 / 1024:.1f} MB)", flush=True)


def main():
    if not BUNDLE.exists():
        raise SystemExit("先运行 scripts/build_scene.py")
    config = load_config()
    session = DemoSession.load(BUNDLE, rgb_root=config["paths"].get("rgb_root") or "")
    ready = session.rgb_ready_count()
    if ready < session.n_frames:
        raise SystemExit(f"原图还没下完：{ready}/{session.n_frames}。先运行 scripts/download_rgb.py")
    encode(session, PLAIN, show_boxes=False)
    encode(session, BOXES, show_boxes=True)


if __name__ == "__main__":
    main()
