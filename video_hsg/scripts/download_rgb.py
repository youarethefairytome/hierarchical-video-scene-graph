"""从 CODa 序列 0 的 zip 里只拉取 cam0 原图。

HSGG 用的是每隔 10 帧的一张图，文件名末尾的数字就是 CODa 帧号。
整包 zip 约 42GB，这里用 HTTP Range 只取需要的 PNG。
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
import threading
import time
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

ZIP_URL = "https://web.corral.tacc.utexas.edu/texasrobotics/web_CODa/sequences/0.zip"
CD_OFFSET = 44736369464
CD_SIZE = 3203401
SCENE_FRAMES = ROOT.parent / "HSGG_NAVQA_JSON" / "hsgg_navqa_seq0_every10_full" / "frame_scene_graphs"
CD_CACHE = ROOT / "data" / "seq0_cd.bin"
RGB_DIR = ROOT / "data" / "rgb" / "navqa_seq0"


def fetch_range(url: str, start: int, end: int, timeout: int = 180) -> bytes:
    expected = end - start + 1
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            request = urllib.request.Request(
                url,
                headers={"Range": f"bytes={start}-{end}", "User-Agent": "video-hsg"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = response.read()
            if len(data) != expected:
                raise OSError(f"短读 {len(data)} / {expected}")
            return data
        except Exception as exc:
            last_error = exc
            time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"下载失败 {start}-{end}: {last_error}")


def _zip64_values(extra: bytes) -> list[int]:
    values: list[int] = []
    pos = 0
    while pos + 4 <= len(extra):
        header_id, size = struct.unpack_from("<HH", extra, pos)
        body = extra[pos + 4 : pos + 4 + size]
        if header_id == 1:
            for offset in range(0, len(body) - 7, 8):
                values.append(struct.unpack_from("<Q", body, offset)[0])
        pos += 4 + size
    return values


def load_central_directory() -> bytes:
    CD_CACHE.parent.mkdir(parents=True, exist_ok=True)
    if CD_CACHE.exists() and CD_CACHE.stat().st_size == CD_SIZE:
        return CD_CACHE.read_bytes()
    print("下载 zip 中央目录", flush=True)
    data = fetch_range(ZIP_URL, CD_OFFSET, CD_OFFSET + CD_SIZE - 1)
    CD_CACHE.write_bytes(data)
    return data


def parse_cam0(cd: bytes) -> dict[int, dict]:
    pos = 0
    found: dict[int, dict] = {}
    while pos + 46 <= len(cd) and cd[pos : pos + 4] == b"PK\x01\x02":
        method = struct.unpack_from("<H", cd, pos + 10)[0]
        comp_size, uncomp_size = struct.unpack_from("<II", cd, pos + 20)
        name_len, extra_len, comment_len = struct.unpack_from("<HHH", cd, pos + 28)
        local_off = struct.unpack_from("<I", cd, pos + 42)[0]
        name = cd[pos + 46 : pos + 46 + name_len].decode("utf-8", "replace")
        extra = cd[pos + 46 + name_len : pos + 46 + name_len + extra_len]
        pos += 46 + name_len + extra_len + comment_len
        if not name.startswith("2d_rect/cam0/"):
            continue
        values = _zip64_values(extra)
        index = 0
        if uncomp_size == 0xFFFFFFFF:
            uncomp_size = values[index]
            index += 1
        if comp_size == 0xFFFFFFFF:
            comp_size = values[index]
            index += 1
        if local_off == 0xFFFFFFFF:
            local_off = values[index]
            index += 1
        frame = int(name.rsplit("_", 1)[-1].split(".")[0])
        found[frame] = {
            "name": name,
            "method": method,
            "comp_size": comp_size,
            "uncomp_size": uncomp_size,
            "local_off": local_off,
        }
    return found


def needed_frames() -> list[int]:
    frames = []
    for path in SCENE_FRAMES.glob("*.json"):
        match = re.search(r"_(\d+)$", path.stem)
        if not match:
            raise ValueError(f"无法从文件名得到帧号: {path.name}")
        frames.append(int(match.group(1)))
    return sorted(set(frames))


def data_offset(entry: dict) -> int:
    head = fetch_range(ZIP_URL, entry["local_off"], entry["local_off"] + 29)
    if head[:4] != b"PK\x03\x04":
        raise ValueError(f"本地文件头签名不对: {entry['name']}")
    name_len, extra_len = struct.unpack_from("<HH", head, 26)
    return entry["local_off"] + 30 + name_len + extra_len


def decode_entry(entry: dict, blob: bytes) -> bytes:
    if entry["method"] == 0:
        return blob
    if entry["method"] == 8:
        return zlib.decompress(blob, -15)
    raise ValueError(f"不支持的压缩方式 {entry['method']}: {entry['name']}")


def download_one(frame: int, entry: dict, output_dir: Path) -> tuple[int, int]:
    destination = output_dir / f"2d_rect_cam0_0_{frame}.png"
    if destination.exists() and destination.stat().st_size > 1000:
        return frame, destination.stat().st_size
    offset = data_offset(entry)
    blob = fetch_range(ZIP_URL, offset, offset + entry["comp_size"] - 1)
    raw = decode_entry(entry, blob)
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"帧 {frame} 不是 PNG")
    temporary = destination.with_suffix(".part")
    temporary.write_bytes(raw)
    temporary.replace(destination)
    return frame, len(raw)


def main():
    parser = argparse.ArgumentParser(description="下载 NavQA seq0 对应的 CODa cam0 原图")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    frames = needed_frames()
    if args.limit is not None:
        frames = frames[: args.limit]
    catalog = parse_cam0(load_central_directory())
    missing = [frame for frame in frames if frame not in catalog]
    if missing:
        raise SystemExit(f"zip 里找不到这些帧: {missing[:8]}")
    RGB_DIR.mkdir(parents=True, exist_ok=True)
    print(f"需要 {len(frames)} 张，目录 {RGB_DIR}", flush=True)
    done = 0
    total_bytes = 0
    lock = threading.Lock()
    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(download_one, frame, catalog[frame], RGB_DIR) for frame in frames]
        for future in as_completed(futures):
            frame, size = future.result()
            with lock:
                done += 1
                total_bytes += size
                if done % 20 == 0 or done == len(frames):
                    elapsed = max(time.time() - started, 0.1)
                    print(
                        f"  {done}/{len(frames)}  {total_bytes / 1024 / 1024:.0f} MB  "
                        f"{total_bytes / 1024 / 1024 / elapsed:.1f} MB/s  last={frame}",
                        flush=True,
                    )
    print("download done", flush=True)


if __name__ == "__main__":
    main()
