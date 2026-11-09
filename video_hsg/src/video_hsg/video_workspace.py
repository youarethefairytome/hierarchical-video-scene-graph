"""按视频绑定场景图，供所有标签页共享；不保存进程级的“当前视频”。"""
from __future__ import annotations

import json
import math
import threading
from html import escape
from pathlib import Path

import cv2
from PIL import Image

from video_hsg.analysis import AnalysisWorkspace
from video_hsg.service import DemoSession


def read_video_frame(video: dict, index: int) -> Image.Image:
    capture = cv2.VideoCapture(video["path"])
    try:
        capture.set(cv2.CAP_PROP_POS_FRAMES, min(max(int(index), 0), video["frames"] - 1))
        ok, frame = capture.read()
        if not ok:
            raise ValueError("当前视频的画面读取失败，请检查视频文件。")
        return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    finally:
        capture.release()


class _VideoDemoSession(DemoSession):
    def __init__(self, bundle: dict, video: dict, rgb_root: str):
        super().__init__(bundle, rgb_root=rgb_root)
        self.video = video

    def _base_image(self, frame: dict):
        # 优先使用明确绑定的原图；没有原图时从同一视频读取，而不是画旧背景。
        image = super()._base_image(frame)
        if image is not None:
            return image
        index = frame["frame_id"] if self.video.get("graph_frame_mapping") == "sampled_video" else frame["source_frame"]
        return read_video_frame(self.video, index)


class VideoScene:
    def __init__(self, video: dict, session: DemoSession | None = None,
                 bundle_path: Path | None = None, reason: str = "尚无对应的场景图缓存。"):
        self.video = video
        self.session = session
        self.bundle_path = bundle_path
        self.reason = reason
        self.n_frames = session.n_frames if session else max(1, min(video["frames"], math.ceil(video["duration"] * 8)))
        self._preview_cache: dict[int, Image.Image] = {}

    @property
    def has_graph(self) -> bool:
        return self.session is not None

    @property
    def top_labels(self):
        return self.session.top_labels if self.session else []

    @property
    def notice(self):
        title = escape(self.video["title"])
        if not self.session:
            return f"当前视频：**{title}**。{self.reason} 当前仅展示已有 HSGG 结果；此视频可预览，接入对应结果后开放图、轨迹和查询。"
        summary = self.session.summary
        source = "HSGG 预处理结果"
        return (f"当前视频：**{title}** · {source} · **{summary['frame_count']}** 采样帧 · "
                f"**{summary['tracks']}** 轨迹 · **{summary['event_count']}** 事件 · **{summary['clip_count']}** Clip。所有页面使用同一视频。")

    def video_file(self, boxes: bool = False):
        path = self.video.get("boxes_video") if boxes and self.has_graph else None
        return path if path and Path(path).is_file() else self.video["path"]

    def _payload(self, payload: dict):
        return json.dumps({**payload, "video_id": self.video["id"],
                           "title": f"{self.video['title']} · {payload.get('title', '')}"}, ensure_ascii=False)

    def timeline_json(self):
        if self.session:
            return self._payload(json.loads(self.session.timeline_json()))
        return self._payload({"title": self.reason, "nodes": [], "links": [], "frame_count": self.n_frames,
                              "source_frames": [], "counts": {1: 0, 2: 0, 3: 0}})

    def layered_json(self, frame_id: int):
        if self.session:
            return self._payload(json.loads(self.session.layered_json(frame_id)))
        return self._payload({"title": self.reason, "nodes": [], "edges": []})

    def frame_view(self, frame_id: int, show_parts=False, highlight=None, show_boxes=True):
        frame_id = min(max(int(frame_id), 0), self.n_frames - 1)
        if self.session:
            view = self.session.frame_view(frame_id, show_parts, highlight or [], show_boxes=show_boxes)
            return {**view, "info": f"**{escape(self.video['title'])}** · {view['info']}"}
        index = round(frame_id * (self.video["frames"] - 1) / max(self.n_frames - 1, 1))
        if index not in self._preview_cache:
            self._preview_cache[index] = read_video_frame(self.video, index)
            if len(self._preview_cache) > 16:
                self._preview_cache.pop(next(iter(self._preview_cache)))
        return {"frame_id": frame_id, "frame": self._preview_cache[index],
                "info": f"**{escape(self.video['title'])}** · 预览帧 {frame_id} / {self.n_frames - 1} · "
                        f"{index / self.video['fps']:.2f} 秒 · 未绑定 HSGG 结果 · 仅预览"}

    def view(self, frame_id: int, show_parts=False, highlight=None, show_boxes=True):
        if self.session:
            view = self.session.view(frame_id, show_parts, highlight or [], show_boxes=show_boxes)
            return {**view, "info": f"**{escape(self.video['title'])}** · {view['info']}",
                    "layered": self._payload(json.loads(view["layered"]))}
        return {**self.frame_view(frame_id), "layered": self.layered_json(frame_id),
                "timeline": None, "clip_graph": None, "video_graph": None,
                "entities": [], "relations": [], "clip_text": self.notice}

    def search(self, text: str, kind: str):
        return self.session.search(text, kind) if self.session else []

    @property
    def comparison(self):
        return self.session.summary.get("comparison", "") if self.session else self.notice

    @property
    def neo4j_text(self):
        if not self.session or not self.bundle_path:
            return "当前视频暂无图数据，尚未生成对应的 Neo4j 导出文件。"
        folder = self.bundle_path.parent / "neo4j"
        if not (folder / "browser.cypher").is_file():
            return "当前视频已有场景图，尚未生成 Neo4j 导出文件。"
        return ("Track、Clip、Event 是节点；关系来自当前视频的预处理结果。\n\n"
                f"在 Neo4j Browser 中执行：`{folder / 'browser.cypher'}`。\n\n完整 CSV 在同一目录。")


class VideoSceneRegistry:
    def __init__(self, workspace: AnalysisWorkspace):
        self.workspace = workspace
        self._cache: dict[str, tuple[tuple, VideoScene]] = {}
        self._lock = threading.RLock()

    def _path(self, value: str | None):
        if not value:
            return None
        path = Path(value)
        return (self.workspace.root / path).resolve() if not path.is_absolute() else path

    def get(self, video_id: str) -> VideoScene:
        video = self.workspace.video(video_id)
        path = self._path(video.get("scene_bundle"))
        key = (json.dumps(video, sort_keys=True), str(path), path.stat().st_mtime_ns if path and path.is_file() else None)
        with self._lock:
            cached = self._cache.get(video_id)
            if cached and cached[0] == key:
                return cached[1]
            for name in ("rgb_root", "boxes_video"):
                resolved = self._path(video.get(name))
                video[name] = str(resolved) if resolved else ""
            reason = "尚无对应的场景图缓存。"
            session = None
            if path and path.is_file():
                try:
                    bundle = json.loads(path.read_text(encoding="utf-8"))
                    expected = video.get("scene_video_sha256") or bundle.get("meta", {}).get("video_sha256")
                    source_id = video.get("scene_source_id")
                    if not expected or expected != video["sha256"]:
                        raise ValueError("场景图缺少匹配的视频指纹或指纹不一致，已停止使用该结果。")
                    if source_id and source_id != bundle.get("meta", {}).get("scene_id"):
                        raise ValueError("绑定的场景编号不一致，已停止使用该结果。")
                    frames = bundle.get("frames") or []
                    if not frames:
                        raise ValueError("对应的场景图没有有效帧。")
                    mode = video.get("graph_frame_mapping", "source_frame")
                    if mode == "sampled_video":
                        if len(frames) != video["frames"]:
                            raise ValueError("采样视频与场景图帧数不一致，已停止使用该结果。")
                    elif mode != "source_frame" or any(not 0 <= int(f["source_frame"]) < video["frames"] for f in frames):
                        raise ValueError("场景图帧号不能对应到当前视频，已停止使用该结果。")
                    session = _VideoDemoSession(bundle, video, video.get("rgb_root", ""))
                except (ValueError, KeyError, TypeError, OSError) as error:
                    reason = f"HSGG 绑定无效：{error}"
            scene = VideoScene(video, session, path, reason)
            self._cache[video_id] = (key, scene)
            return scene
