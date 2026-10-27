"""整段视频的三层散点：X 是帧时间，Z 是数据里的 L1 / L2 / L3。"""

from __future__ import annotations

import json
from pathlib import Path

LAYER_COLORS = {1: "#3b6ea5", 2: "#2f8f6b", 3: "#c47b00"}


def hierarchy_sets(hierarchy: dict | None) -> tuple[set[str], set[str]]:
    hierarchy = hierarchy or {}
    layer2: set[str] = set()
    layer3: set[str] = set()
    for kids in (hierarchy.get("layer2_mapping") or {}).values():
        if isinstance(kids, list):
            layer2.update(str(item) for item in kids)
    for kids in (hierarchy.get("layer3_mapping") or {}).values():
        if isinstance(kids, list):
            layer3.update(str(item) for item in kids)
    return layer2, layer3


def parent_links(hierarchy: dict | None) -> list[tuple[str, str]]:
    """只取 layer2 / layer3 的父子从属，不取 near、has 这类关系。"""
    hierarchy = hierarchy or {}
    pairs: list[tuple[str, str]] = []
    for key in ("layer2_mapping", "layer3_mapping"):
        for parent, kids in (hierarchy.get(key) or {}).items():
            if not isinstance(kids, list):
                continue
            parent_name = str(parent)
            for kid in kids:
                pairs.append((parent_name, str(kid)))
    return pairs


def layer_of(name: str, layer2: set[str], layer3: set[str]) -> int:
    """L3 只认 hierarchy.layer3_mapping 里的子节点，不用属性层。"""
    if name in layer3:
        return 3
    if name in layer2:
        return 2
    return 1


def build_timeline_layers(frames: list[dict], scene_dir: Path) -> dict:
    folder = scene_dir / "frame_scene_graphs"
    nodes: list[list] = []
    links: list[list[int]] = []
    source_frames: list[int] = []
    counts = {1: 0, 2: 0, 3: 0}
    for frame in frames:
        source_frames.append(int(frame.get("source_frame") or frame["frame_id"]))
        raw_path = folder / f"{frame.get('key', '')}.json"
        hierarchy = {}
        if raw_path.is_file():
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            hierarchy = raw.get("hierarchy") or {}
        layer2, layer3 = hierarchy_sets(hierarchy)
        width = float(frame.get("width") or 1) or 1.0
        index_of: dict[str, int] = {}
        for entity in frame["entities"]:
            name = entity["local_name"]
            layer = layer_of(name, layer2, layer3)
            box = entity.get("bbox") or [0, 0, 0, 0]
            center_x = (float(box[0]) + float(box[2])) / 2 / width
            y = round((center_x - 0.5) * 10, 3)
            index_of[name] = len(nodes)
            nodes.append(
                [
                    int(frame["frame_id"]),
                    layer,
                    y,
                    name,
                    entity.get("track_id") or "",
                    entity.get("canonical_label") or "",
                ]
            )
            counts[layer] += 1
        for parent_name, child_name in parent_links(hierarchy):
            parent_index = index_of.get(parent_name)
            child_index = index_of.get(child_name)
            if parent_index is None or child_index is None:
                continue
            links.append([parent_index, child_index])
    return {
        "title": "全视频三层  ·  X 时间  ·  Z 为 L1 / L2 / L3",
        "frame_count": len(frames),
        "source_frames": source_frames,
        "counts": counts,
        "nodes": nodes,
        "links": links,
    }
