"""实体、关系和事件的检索直接扫预处理结果，Demo 不需要向量库。"""

from __future__ import annotations

import re

from video_hsg.normalize.labels import canonical_label, normalize_predicate

ENTITY_COLUMNS = ["起始采样帧", "结束采样帧", "原始帧起", "原始帧止", "类型", "描述", "主体轨迹", "客体轨迹", "置信度"]


def _contains(query: str, predicate_norm: str, *parts: str) -> bool:
    needles = {query, query.replace(" ", "_")}
    if predicate_norm:
        needles.add(predicate_norm)
    for part in parts:
        text = (part or "").lower()
        if not text:
            continue
        if len(query) <= 3:
            tokens = set(re.findall(r"[a-z0-9_]+", text))
            if needles & tokens:
                return True
            continue
        if any(needle and needle in text for needle in needles):
            return True
    return False


def search_bundle(bundle: dict, text: str, kind: str, limit: int = 200) -> list[list]:
    query = text.strip().lower()
    if not query:
        return []
    predicate_norm = normalize_predicate(query)
    label_norm = canonical_label(query)
    rows: list[list] = []

    if kind in ("全部", "实体"):
        for track in bundle["tracks"]:
            canonical = (track.get("canonical_label") or "").lower()
            raw = (track.get("raw_label") or "").lower()
            track_id = (track.get("track_id") or "").lower()
            label_hit = (
                (bool(label_norm) and label_norm == canonical)
                or query in {canonical, raw, track_id}
                or (len(query) > 3 and (query in canonical or query in raw or query in track_id))
            )
            attribute_hit = _contains(query, predicate_norm, " ".join(track.get("attributes") or []))
            if kind == "实体" and not label_hit:
                continue
            if kind == "全部" and not (label_hit or attribute_hit):
                continue
            attribute = (track.get("attributes") or [""])[0]
            description = f"{track['canonical_label']} {track['track_id']}"
            if attribute:
                description += f" | {attribute[:80]}"
            rows.append(
                [
                    track["start_frame"],
                    track["end_frame"],
                    track["start_source_frame"],
                    track["end_source_frame"],
                    "实体",
                    description,
                    track["track_id"],
                    "-",
                    "",
                ]
            )

    if kind in ("全部", "关系"):
        for relation in bundle["temporal_relations"]:
            if not _contains(
                query,
                predicate_norm,
                relation["predicate"],
                relation["subject_label"],
                relation["object_label"],
                relation["subject_track_id"],
                relation["object_track_id"],
            ):
                continue
            rows.append(
                [
                    relation["start_frame"],
                    relation["end_frame"],
                    relation["start_source_frame"],
                    relation["end_source_frame"],
                    "关系",
                    f"{relation['subject_label']} —{relation['predicate']}→ {relation['object_label']}",
                    relation["subject_track_id"],
                    relation["object_track_id"],
                    relation["confidence"],
                ]
            )

    if kind in ("全部", "事件"):
        for event in bundle["events"]:
            if kind == "全部" and event.get("source") != "transition":
                continue
            if not _contains(
                query,
                predicate_norm,
                event["action"],
                event["subject_label"],
                event["object_label"],
                event["subject_track_id"],
                event["object_track_id"],
            ):
                continue
            rows.append(
                [
                    event["start_frame"],
                    event["end_frame"],
                    event["start_source_frame"],
                    event["end_source_frame"],
                    "事件",
                    f"{event['subject_label']} —{event['action']}→ {event['object_label']}",
                    event["subject_track_id"],
                    event["object_track_id"],
                    event["confidence"],
                ]
            )

    rows.sort(key=lambda row: (row[0], row[4], row[5]))
    return rows[:limit]
