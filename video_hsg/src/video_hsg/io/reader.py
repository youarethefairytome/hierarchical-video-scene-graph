"""从 frame_scene_graphs/*.json 读取单帧层次场景图。

帧内的 person1 / window2 只在这一帧有效。这里把它变成 FrameEntity，
不把它当成全局 ID。
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from video_hsg.normalize.labels import attribute_tokens, canonical_label, normalize_predicate
from video_hsg.schemas import FrameEntity, FrameGraph, FrameRelation


def make_local_names(labels: list[str]) -> list[str]:
    """同一帧里重复类别按出现顺序加 1、2、3；只出现一次的类别不加后缀。"""
    counts = Counter(labels)
    seen: dict[str, int] = defaultdict(int)
    names: list[str] = []
    for label in labels:
        seen[label] += 1
        if counts[label] == 1:
            names.append(label)
        else:
            names.append(f"{label}{seen[label]}")
    return names


def source_frame_from_name(stem: str, fallback: int) -> int:
    match = re.search(r"_(\d+)$", stem)
    if match:
        return int(match.group(1))
    return fallback


def _as_mapping(value) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _attribute_map(raw, warnings: list[str], filename: str) -> dict[int, str]:
    mapped: dict[int, str] = {}
    if raw is None:
        return mapped
    if isinstance(raw, dict):
        items = raw.items()
    elif isinstance(raw, list):
        items = enumerate(raw)
    else:
        warnings.append(f"{filename}: attributes 不是对象或数组，已忽略")
        return mapped
    for key, value in items:
        try:
            index = int(key)
        except (TypeError, ValueError):
            warnings.append(f"{filename}: 无法解析属性下标 {key!r}")
            continue
        if value is None:
            continue
        mapped[index] = str(value)
    return mapped


def read_frame(path: Path, frame_id: int, image_cfg: dict, warnings: list[str]) -> tuple[FrameGraph, int]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"无法解析 {path.name}: {exc}") from exc
    if not isinstance(data, dict) or "objects" not in data:
        raise ValueError(f"{path.name} 缺少 objects")

    objects = data["objects"] or {}
    boxes = objects.get("boxes") or []
    labels = objects.get("labels") or []
    scores = objects.get("scores") or []
    if not (len(boxes) == len(labels) == len(scores)):
        raise ValueError(
            f"{path.name} 的 boxes/labels/scores 长度不一致: "
            f"{len(boxes)}, {len(labels)}, {len(scores)}"
        )

    names = make_local_names([str(label) for label in labels])
    attributes = _attribute_map(data.get("attributes"), warnings, path.name)
    hierarchy = _as_mapping(data.get("hierarchy"))
    parent_of: dict[str, str] = {}
    children_of: dict[str, list[str]] = defaultdict(list)
    for layer_name in ("layer2_mapping", "layer3_mapping"):
        for parent, kids in _as_mapping(hierarchy.get(layer_name)).items():
            parent_name = str(parent)
            for kid in _as_list(kids):
                parent_of[kid] = parent_name
                children_of[parent_name].append(kid)

    width = int(image_cfg["width"])
    height = int(image_cfg["height"])
    if boxes:
        width = max(width, int(math.ceil(max(float(box[2]) for box in boxes))))
        height = max(height, int(math.ceil(max(float(box[3]) for box in boxes))))

    entities: list[FrameEntity] = []
    for index, (box, label, score, local_name) in enumerate(zip(boxes, labels, scores, names)):
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            raise ValueError(f"{path.name} 的第 {index} 个框不是长度为 4 的数组")
        entity = FrameEntity(
            frame_id=frame_id,
            local_index=index,
            local_name=local_name,
            label=str(label),
            canonical_label=canonical_label(str(label)),
            bbox=[float(value) for value in box],
            score=float(score),
            attribute_text=attributes.get(index),
            parent_local_name=parent_of.get(local_name),
            child_local_names=list(children_of.get(local_name, [])),
        )
        entity.attr_tokens = attribute_tokens(entity.attribute_text)
        entities.append(entity)

    by_name = {entity.local_name: entity for entity in entities}
    for entity in entities:
        parent = by_name.get(entity.parent_local_name or "")
        if parent is not None:
            entity.parent_canonical = parent.canonical_label
        entity.child_canonicals = [
            by_name[name].canonical_label for name in entity.child_local_names if name in by_name
        ]

    relations: list[FrameRelation] = []
    mismatches = 0
    raw_relations = data.get("relations") or []
    if not isinstance(raw_relations, list):
        raise ValueError(f"{path.name} 的 relations 不是数组")
    for relation in raw_relations:
        if not isinstance(relation, dict):
            warnings.append(f"{path.name}: 跳过一条不是对象的 relation")
            continue
        idx = relation.get("idx") or []
        if not isinstance(idx, (list, tuple)) or len(idx) != 2:
            warnings.append(f"{path.name}: relation 缺少 idx，已跳过")
            continue
        try:
            subject_index = int(idx[0])
            object_index = int(idx[1])
        except (TypeError, ValueError):
            warnings.append(f"{path.name}: relation idx 无法转成整数，已跳过")
            continue
        if not (0 <= subject_index < len(entities) and 0 <= object_index < len(entities)):
            warnings.append(f"{path.name}: relation idx {idx} 越界，已跳过")
            continue
        subject_label = str(relation.get("subject_label") or "")
        object_label = str(relation.get("object_label") or "")
        if names[subject_index] != subject_label or names[object_index] != object_label:
            mismatches += 1
        relations.append(
            FrameRelation(
                frame_id=frame_id,
                subject_index=subject_index,
                object_index=object_index,
                subject_local_name=subject_label or names[subject_index],
                object_local_name=object_label or names[object_index],
                predicate_raw=str(relation.get("predicate") or ""),
                predicate_norm=normalize_predicate(relation.get("predicate")),
                source=str(relation.get("hsgg_source") or ""),
            )
        )

    for relation in relations:
        subject = entities[relation.subject_index]
        obj = entities[relation.object_index]
        subject.relation_signature.add((relation.predicate_norm, obj.canonical_label))
        obj.relation_signature.add((relation.predicate_norm, subject.canonical_label))

    frame = FrameGraph(
        frame_id=frame_id,
        source_frame=source_frame_from_name(path.stem, frame_id),
        key=path.stem,
        image_path=str(data.get("image_path") or ""),
        width=width,
        height=height,
        entities=entities,
        relations=relations,
    )
    return frame, mismatches


def load_frames(scene_dir: Path, config: dict, max_frames: int | None = None):
    folder = scene_dir / "frame_scene_graphs"
    if not folder.is_dir():
        raise FileNotFoundError(f"缺少帧场景图目录: {folder}")
    files = sorted(folder.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"{folder} 里没有 JSON")
    if max_frames is not None:
        files = files[:max_frames]
    warnings: list[str] = []
    frames: list[FrameGraph] = []
    mismatches = 0
    image_cfg = config["image"]
    for frame_id, path in enumerate(files):
        frame, frame_mismatches = read_frame(path, frame_id, image_cfg, warnings)
        frames.append(frame)
        mismatches += frame_mismatches
    return frames, warnings, mismatches
