"""下载匹配视频，裁剪稳定视角段，聚合已有 HSGG JSON；不进行模型推理。"""
from __future__ import annotations

import json
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path, PurePosixPath

import imageio_ffmpeg
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from video_hsg.analysis import file_hash, video_info
from video_hsg.config import load_config
from video_hsg.pipeline import build_scene

VIDEO_ID = "2535384528"
SCENE = "hsgg_every30_first_half_default_hsgg/49_2535384528"
URL = f"https://huggingface.co/datasets/shuzhig/nextgqa/resolve/main/videos/{VIDEO_ID}.mp4"
SOURCE_SHA256 = "dfe05eb2d7d4509d257d141f676b4103790abb87cdc4afe2512aa7f4ea00272e"


def main():
    archive = ROOT.parent / "HSGG_NEXTQA_JSON" / "hsgg_every30_outputs.tar.gz"
    if not archive.is_file():
        raise FileNotFoundError(f"请先放置已有 HSGG 结果包：{archive}")
    media = ROOT / "data" / "video"
    media.mkdir(parents=True, exist_ok=True)
    source = media / f"nextqa_{VIDEO_ID}_source.mp4"
    display = media / f"nextqa_{VIDEO_ID}_fixed.mp4"
    if not source.exists():
        temporary = source.with_suffix(".download")
        print(f"Downloading {URL}", flush=True)
        try:
            with urllib.request.urlopen(URL, timeout=90) as response, temporary.open("wb") as target:
                while chunk := response.read(1024 * 1024):
                    target.write(chunk)
            if file_hash(temporary) != SOURCE_SHA256:
                raise ValueError("下载视频指纹与已核对的源文件不一致。")
            temporary.replace(source)
        finally:
            temporary.unlink(missing_ok=True)
    if file_hash(source) != SOURCE_SHA256:
        raise ValueError("源视频指纹不匹配。")
    info = video_info(source)
    if (info["frames"], info["width"], info["height"]) != (378, 640, 480) or abs(info["fps"] - 25) > .01:
        raise ValueError("源视频参数与 HSGG extract.log 不一致。")
    if not display.exists():
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
                        "-i", str(source), "-t", "12", "-an", "-c:v", "libx264", "-crf", "18",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(display)], check=True)
    if video_info(display)["frames"] != 300:
        raise ValueError("展示片段应为原视频前 300 帧。")
    # 仅解出指定场景；原始包和 JSON 内容保持不变。
    extracted = ROOT.parent / "HSGG_NEXTQA_JSON"
    with tarfile.open(archive) as handle:
        for member in handle:
            if not member.isfile() or not member.name.startswith(SCENE + "/"):
                continue
            destination = extracted.joinpath(*PurePosixPath(member.name).parts).resolve()
            if not destination.is_relative_to(extracted.resolve()):
                raise ValueError("结果包路径越界。")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with handle.extractfile(member) as content:
                destination.write_bytes(content.read())
    config = load_config()
    output = ROOT / "processed" / f"nextqa_{VIDEO_ID}"
    config["paths"].update(scene_dir=str(extracted / SCENE), output_dir=str(output), rgb_root="")
    config["image"] = {"width": 640, "height": 480}
    config["clip"].update(sampled_frames_per_clip=5, overlap=2)
    # 已有结果每 30 原始帧采样；0..270 均位于展示的 0..299 帧内。
    bundle = build_scene(config, max_frames=10, ablation=True, write=True)
    if [f["source_frame"] for f in bundle["frames"]] != list(range(0, 300, 30)):
        raise ValueError("HSGG 源帧号与采样记录不一致。")
    digest = file_hash(display)
    bundle["meta"].update(dataset="NExT-QA", video_id=VIDEO_ID, source="precomputed_hsgg",
        video_sha256=digest, source_video_sha256=SOURCE_SHA256, source_video_url=URL,
        source_frame_range=[0, 299], source_fps=25, clip_seconds=[0, 12])
    def write(name, data):
        (output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    write("scene_bundle.json", bundle)
    write("summary.json", {"meta": bundle["meta"], "summary": bundle["summary"]})
    write("preparation.json", {"source_url": URL, "source_sha256": SOURCE_SHA256,
        "display_sha256": digest, "source_scene": SCENE, "clip_seconds": [0, 12],
        "sample_source_frames": list(range(0, 300, 30)), "config": config})
    catalog = ROOT / "configs" / "demo_videos.yaml"
    data = yaml.safe_load(catalog.read_text(encoding="utf-8"))
    entry = next(item for item in data["videos"] if item["id"] == f"nextqa_{VIDEO_ID}")
    entry["scene_video_sha256"] = digest
    entry["scene_source_id"] = SCENE.rsplit("/", 1)[-1]
    catalog.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"Ready: {display}; precomputed HSGG frames: {len(bundle['frames'])}", flush=True)


if __name__ == "__main__":
    main()
