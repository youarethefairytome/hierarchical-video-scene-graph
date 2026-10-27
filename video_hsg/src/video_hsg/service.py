"""Demo 读预处理结果。页面回调只调用这里，不重新跑跟踪。"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from video_hsg.query.search import ENTITY_COLUMNS, search_bundle
from video_hsg.visualization.layered import build_layered_scene
from video_hsg.visualization.timeline_layers import build_timeline_layers
from video_hsg.visualization.render import (
    render_frame,
    render_frame_graph,
    render_link_graph,
    render_timeline,
    visible_entities,
)

ENTITY_TABLE_COLUMNS = ["轨迹", "名称", "类别", "置信度", "父节点", "属性"]
RELATION_TABLE_COLUMNS = ["主体", "关系", "客体", "主体轨迹", "客体轨迹"]


class DemoSession:
    def __init__(self, bundle: dict, rgb_root: str = ""):
        self.bundle = bundle
        self.frames = bundle["frames"]
        self.tracks = bundle["tracks"]
        self.relations = bundle["temporal_relations"]
        self.events = bundle["events"]
        self.clips = bundle["clips"]
        self.summary = bundle["summary"]
        self.meta = bundle["meta"]
        self.n_frames = len(self.frames)
        self.rgb_root = Path(rgb_root) if rgb_root else None
        self._video_graph = None
        self._timeline_json: str | None = None
        self._frame_cache: dict[tuple, Image.Image] = {}
        self._clip_cache: dict[tuple, Image.Image] = {}

    @classmethod
    def load(cls, path: Path, rgb_root: str = "") -> "DemoSession":
        bundle = json.loads(path.read_text(encoding="utf-8"))
        return cls(bundle, rgb_root=rgb_root)

    @property
    def top_labels(self) -> list[str]:
        return [label for label, _ in self.summary.get("top_labels", [])]

    def clip_for_frame(self, frame_id: int) -> dict | None:
        covering = [clip for clip in self.clips if clip["start_frame"] <= frame_id <= clip["end_frame"]]
        if not covering:
            return self.clips[0] if self.clips else None
        return min(covering, key=lambda clip: abs(frame_id - (clip["start_frame"] + clip["end_frame"]) / 2))

    def _rgb_path(self, frame: dict) -> Path | None:
        if self.rgb_root is None:
            return None
        source = frame.get("source_frame")
        name = Path(frame.get("image_path") or "").name
        candidates = []
        if name:
            candidates.append(self.rgb_root / name)
            candidates.append(self.rgb_root / Path(name).with_suffix(".png"))
            candidates.append(self.rgb_root / Path(name).with_suffix(".jpg"))
        if source is not None:
            candidates.append(self.rgb_root / f"2d_rect_cam0_0_{source}.png")
            candidates.append(self.rgb_root / f"2d_rect_cam0_0_{source}.jpg")
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _base_image(self, frame: dict) -> Image.Image | None:
        path = self._rgb_path(frame)
        if path is None:
            return None
        with Image.open(path) as image:
            return image.convert("RGB")

    def rgb_ready_count(self) -> int:
        return sum(1 for frame in self.frames if self._rgb_path(frame) is not None)

    def search(self, text: str, kind: str) -> list[list]:
        return search_bundle(self.bundle, text, kind)

    def _video_nodes_edges(self):
        ranked = sorted(
            self.tracks,
            key=lambda track: -(track["observation_count"] * (0.45 if track.get("parent_track_id") else 1)),
        )[:22]
        ids = {track["track_id"] for track in ranked}
        nodes = [
            {"id": track["track_id"], "text": f"{track['canonical_label']}\n{track['track_id'][-5:]}", "color_key": track["track_id"]}
            for track in ranked
        ]
        edges = []
        candidates = [
            relation
            for relation in self.relations
            if relation["subject_track_id"] in ids
            and relation["object_track_id"] in ids
            and relation["end_frame"] - relation["start_frame"] >= 2
            and relation["confidence"] >= 0.6
        ]
        candidates.sort(key=lambda relation: -(relation["end_frame"] - relation["start_frame"]) * relation["confidence"])
        for relation in candidates[:36]:
            edges.append(
                {
                    "source": relation["subject_track_id"],
                    "target": relation["object_track_id"],
                    "label": relation["predicate"],
                }
            )
        return nodes, edges

    def _clip_nodes_edges(self, clip: dict, highlight: set[str]):
        id_set = set(clip["track_ids"])
        members = [track for track in self.tracks if track["track_id"] in id_set]
        members.sort(key=lambda track: -sum(1 for frame_id in track["frame_ids"] if clip["start_frame"] <= frame_id <= clip["end_frame"]))
        pinned = [track for track in members if track["track_id"] in highlight]
        rest = [track for track in members if track["track_id"] not in highlight]
        chosen = (pinned + rest)[:18]
        ids = {track["track_id"] for track in chosen}
        nodes = [
            {"id": track["track_id"], "text": f"{track['canonical_label']}\n{track['track_id'][-5:]}", "color_key": track["track_id"]}
            for track in chosen
        ]
        edges = []
        for relation in self.relations:
            if relation["end_frame"] < clip["start_frame"] or relation["start_frame"] > clip["end_frame"]:
                continue
            if relation["subject_track_id"] in ids and relation["object_track_id"] in ids:
                edges.append(
                    {
                        "source": relation["subject_track_id"],
                        "target": relation["object_track_id"],
                        "label": relation["predicate"],
                    }
                )
            if len(edges) >= 30:
                break
        return nodes, edges

    def _prepare(self, frame_id: int, highlight: list[str] | set[str] | None):
        frame_id = int(max(0, min(int(frame_id), max(self.n_frames - 1, 0))))
        selected = {item for item in (highlight or []) if item and item != "-"}
        return frame_id, selected, self.frames[frame_id]

    def _frame_image(self, frame: dict, show_parts: bool, selected: set[str], show_boxes: bool) -> Image.Image:
        cache_key = (frame["frame_id"], bool(show_parts), bool(show_boxes), tuple(sorted(selected)))
        if cache_key not in self._frame_cache:
            self._frame_cache[cache_key] = render_frame(
                frame,
                show_parts,
                selected,
                self._base_image(frame),
                show_boxes=show_boxes,
            )
            if len(self._frame_cache) > 32:
                self._frame_cache.pop(next(iter(self._frame_cache)))
        return self._frame_cache[cache_key]

    def frame_view(self, frame_id: int, show_parts: bool, highlight: list[str] | set[str] | None, show_boxes: bool = True):
        """播放时只用这一路：原图，以及可选的识别框。不重画轨迹图。"""
        frame_id, selected, frame = self._prepare(frame_id, highlight)
        shown = visible_entities(frame, show_parts, selected) if show_boxes else []
        info = (
            f"采样帧 **{frame_id}** / {self.n_frames - 1}　　"
            f"原始帧 **{frame['source_frame']}**　　"
            f"识别框 {'开' if show_boxes else '关'}"
            f"（显示 {len(shown)}/{len(frame['entities'])}）"
        )
        return {"info": info, "frame": self._frame_image(frame, show_parts, selected, show_boxes), "frame_id": frame_id}

    def timeline_json(self) -> str:
        if self._timeline_json is None:
            scene_dir = Path(self.meta.get("scene_dir") or "")
            payload = build_timeline_layers(self.frames, scene_dir)
            self._timeline_json = json.dumps(payload, ensure_ascii=False)
        return self._timeline_json

    def layered_json(self, frame_id: int) -> str:
        frame_id, _selected, frame = self._prepare(frame_id, [])
        return json.dumps(build_layered_scene(frame), ensure_ascii=False)

    def view(self, frame_id: int, show_parts: bool, highlight: list[str] | set[str] | None, show_boxes: bool = True):
        frame_id, selected, frame = self._prepare(frame_id, highlight)
        clip = self.clip_for_frame(frame_id)
        frame_image = self._frame_image(frame, show_parts, selected, show_boxes)
        frame_graph = render_frame_graph(frame, show_parts, selected)
        layered = json.dumps(build_layered_scene(frame), ensure_ascii=False)
        timeline = render_timeline(self.tracks, frame_id, clip, selected, self.n_frames)
        if self._video_graph is None:
            nodes, edges = self._video_nodes_edges()
            self._video_graph = render_link_graph("VideoGraph（长轨迹与稳定关系）", nodes, edges)
        clip_key = (clip["clip_id"] if clip else "none", tuple(sorted(selected)))
        if clip_key not in self._clip_cache:
            if clip:
                nodes, edges = self._clip_nodes_edges(clip, selected)
                title = f"{clip['clip_id']}  采样帧 {clip['start_frame']}–{clip['end_frame']}"
                self._clip_cache[clip_key] = render_link_graph(title, nodes, edges)
            else:
                self._clip_cache[clip_key] = render_link_graph("ClipGraph", [], [])
            if len(self._clip_cache) > 24:
                self._clip_cache.pop(next(iter(self._clip_cache)))

        shown = visible_entities(frame, show_parts, selected)
        shown_indexes = {entity["local_index"] for entity in shown}
        entities = sorted(shown, key=lambda entity: -float(entity["score"]))[:40]
        entity_rows = [
            [
                entity.get("track_id") or "-",
                entity["local_name"],
                entity["canonical_label"],
                round(float(entity["score"]), 3),
                entity.get("parent_local_name") or "-",
                (entity.get("attribute_text") or "")[:80],
            ]
            for entity in entities
        ]
        relation_rows = []
        for relation in frame["relations"]:
            if relation["subject_index"] not in shown_indexes and relation["object_index"] not in shown_indexes:
                continue
            relation_rows.append(
                [
                    relation["subject_local_name"],
                    relation["predicate"],
                    relation["object_local_name"],
                    relation.get("subject_track_id") or "-",
                    relation.get("object_track_id") or "-",
                ]
            )
            if len(relation_rows) >= 60:
                break
        info = (
            f"采样帧 **{frame_id}** / {self.n_frames - 1}　　"
            f"原始帧 **{frame['source_frame']}**　　"
            f"实体 {len(frame['entities'])}（显示 {len(shown)}）　　"
            f"关系 {len(frame['relations'])}"
        )
        if clip:
            clip_text = (
                f"**{clip['clip_id']}**　采样帧 {clip['start_frame']}–{clip['end_frame']}"
                f"（原始帧 {clip['start_source_frame']}–{clip['end_source_frame']}）\n\n{clip['summary']}"
            )
        else:
            clip_text = "没有 Clip。"
        return {
            "info": info,
            "frame": frame_image,
            "frame_graph": frame_graph,
            "layered": layered,
            "timeline": timeline,
            "clip_graph": self._clip_cache[clip_key],
            "video_graph": self._video_graph,
            "entities": entity_rows,
            "relations": relation_rows,
            "clip_text": clip_text,
            "frame_id": frame_id,
        }


__all__ = [
    "ENTITY_COLUMNS",
    "ENTITY_TABLE_COLUMNS",
    "RELATION_TABLE_COLUMNS",
    "DemoSession",
]
