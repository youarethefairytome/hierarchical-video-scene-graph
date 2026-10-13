"""跨帧实体关联。

V1 使用 IoU、中心、尺度、类别，加上属性、层次和关系邻域。
分配用匈牙利算法。轨迹状态是 tentative / confirmed / lost / removed。
高分检测先匹配，低分检测只用来找回已有轨迹，这是 ByteTrack 的两阶段。
被移除的已确认轨迹可以在短间隔后恢复，这是 OC-SORT 式的观测恢复。
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
from scipy.optimize import linear_sum_assignment

from video_hsg.schemas import EntityTrack, FrameEntity, FrameGraph, Observation
from video_hsg.tracking.geometry import pairwise_center, pairwise_iou, pairwise_size

COMPONENT_KEYS = ("iou", "center", "size", "label", "attribute", "hierarchy", "relation")


def jaccard(left, right) -> float:
    if not left or not right:
        return 0.0
    left_set = set(left)
    right_set = set(right)
    union = left_set | right_set
    if not union:
        return 0.0
    return len(left_set & right_set) / len(union)


def hierarchy_similarity(track: EntityTrack, entity: FrameEntity) -> float:
    parts: list[float] = []
    if track.parent_canonical and entity.parent_canonical:
        parts.append(1.0 if track.parent_canonical == entity.parent_canonical else 0.0)
    if track.child_canonicals and entity.child_canonicals:
        parts.append(jaccard(track.child_canonicals, entity.child_canonicals))
    if not parts:
        return 0.0
    return sum(parts) / len(parts)


def score_matrices(tracks: list[EntityTrack], entities: list[FrameEntity], frame: FrameGraph, cfg: dict):
    count_t = len(tracks)
    count_e = len(entities)
    scores = np.zeros((count_t, count_e), dtype=np.float32)
    components = {key: np.zeros((count_t, count_e), dtype=np.float32) for key in COMPONENT_KEYS}
    if count_t == 0 or count_e == 0:
        return scores, components

    boxes_t = np.asarray([track.observations[-1].bbox for track in tracks], dtype=np.float32)
    boxes_e = np.asarray([entity.bbox for entity in entities], dtype=np.float32)
    iou = pairwise_iou(boxes_t, boxes_e)
    distance, center = pairwise_center(boxes_t, boxes_e, frame.width, frame.height, cfg["center_sigma"])
    size = pairwise_size(boxes_t, boxes_e)

    use_attr = float(cfg["weight_attribute"]) > 0
    use_hier = float(cfg["weight_hierarchy"]) > 0
    use_rel = float(cfg["weight_relation"]) > 0
    center_gate = float(cfg["center_gate"])
    min_iou = float(cfg["min_iou_gate"])

    for i, track in enumerate(tracks):
        for j, entity in enumerate(entities):
            if track.canonical_label != entity.canonical_label:
                continue
            if distance[i, j] >= center_gate and iou[i, j] < min_iou:
                continue
            attr = jaccard(track.recent_attr_tokens, entity.attr_tokens) if use_attr else 0.0
            hier = hierarchy_similarity(track, entity) if use_hier else 0.0
            rel = jaccard(track.relation_signature, entity.relation_signature) if use_rel else 0.0
            total = (
                float(cfg["weight_iou"]) * float(iou[i, j])
                + float(cfg["weight_center"]) * float(center[i, j])
                + float(cfg["weight_size"]) * float(size[i, j])
                + float(cfg["weight_label"]) * 1.0
                + float(cfg["weight_attribute"]) * attr
                + float(cfg["weight_hierarchy"]) * hier
                + float(cfg["weight_relation"]) * rel
            )
            scores[i, j] = total
            components["iou"][i, j] = iou[i, j]
            components["center"][i, j] = center[i, j]
            components["size"][i, j] = size[i, j]
            components["label"][i, j] = 1.0
            components["attribute"][i, j] = attr
            components["hierarchy"][i, j] = hier
            components["relation"][i, j] = rel
    return scores, components


def associate(tracks: list[EntityTrack], entities: list[FrameEntity], frame: FrameGraph, cfg: dict):
    if not tracks or not entities:
        return []
    scores, components = score_matrices(tracks, entities, frame, cfg)
    threshold = float(cfg["match_threshold"])
    cost = np.full(scores.shape, 1e3, dtype=np.float64)
    valid = scores >= threshold
    cost[valid] = 1.0 - scores[valid]
    if not np.any(valid):
        return []
    rows, cols = linear_sum_assignment(cost)
    matches = []
    for row, col in zip(rows, cols):
        if scores[row, col] < threshold:
            continue
        comps = {key: float(components[key][row, col]) for key in COMPONENT_KEYS}
        matches.append((int(row), int(col), float(scores[row, col]), comps))
    return matches


def _update_track(track: EntityTrack, entity: FrameEntity, match_score: float | None, min_hits: int):
    track.observations.append(
        Observation(
            frame_id=entity.frame_id,
            local_index=entity.local_index,
            local_name=entity.local_name,
            bbox=list(entity.bbox),
            score=entity.score,
            attribute_text=entity.attribute_text,
            match_score=match_score,
        )
    )
    track.end_frame = entity.frame_id
    track.hits += 1
    track.missed_count = 0
    track.status = "confirmed" if track.hits >= min_hits else "tentative"
    if entity.attribute_text and entity.attribute_text not in track.attributes:
        track.attributes.append(entity.attribute_text)
        track.attributes = track.attributes[-8:]
    track.attr_history.append(set(entity.attr_tokens))
    track.attr_history = track.attr_history[-3:]
    tokens: set[str] = set()
    for part in track.attr_history:
        tokens |= part
    track.recent_attr_tokens = tokens
    track.parent_canonical = entity.parent_canonical
    track.child_canonicals = frozenset(entity.child_canonicals)
    track.relation_signature = frozenset(entity.relation_signature)
    entity.track_id = track.track_id


def _create_track(number: int, entity: FrameEntity, min_hits: int) -> EntityTrack:
    track = EntityTrack(
        track_id=f"track_{number:05d}",
        canonical_label=entity.canonical_label,
        raw_label=entity.label,
        status="tentative",
        start_frame=entity.frame_id,
        end_frame=entity.frame_id,
        observations=[],
    )
    _update_track(track, entity, None, min_hits)
    return track


def _mark_missed(track: EntityTrack, cfg: dict):
    track.missed_count += 1
    if track.hits < int(cfg["min_confirm_hits"]):
        if track.missed_count > int(cfg["tentative_max_missed"]):
            track.status = "removed"
        else:
            track.status = "lost"
        return
    track.status = "lost"
    if track.missed_count > int(cfg["max_missed_frames"]):
        track.status = "removed"


def _revive(tracks: list[EntityTrack], entities: list[FrameEntity], frame: FrameGraph, cfg: dict):
    gap = int(cfg["revive_max_gap"])
    if gap <= 0 or not entities:
        return []
    min_hits = int(cfg["min_confirm_hits"])
    candidates = [
        track
        for track in tracks
        if track.status == "removed"
        and track.hits >= min_hits
        and 0 < frame.frame_id - track.end_frame <= gap
    ]
    if not candidates:
        return []
    revived_cfg = dict(cfg)
    revived_cfg["match_threshold"] = float(cfg["revive_min_score"])
    matches = associate(candidates, entities, frame, revived_cfg)
    return [(candidates[ti], entities[ei], total, comps) for ti, ei, total, comps in matches]


def _accumulate(stats: dict, total: float, comps: dict):
    stats["n"] += 1
    stats["total"] += total
    for key in COMPONENT_KEYS:
        stats[key] += comps[key]


def _finish_stats(stats: dict) -> dict:
    count = int(stats["n"])
    finished = {"accepted_matches": count}
    for key in list(COMPONENT_KEYS) + ["total"]:
        finished[f"mean_{key}"] = round(stats[key] / count, 3) if count else 0.0
    return finished


def track_frames(frames: list[FrameGraph], cfg: dict, progress: bool = False):
    for frame in frames:
        for entity in frame.entities:
            entity.track_id = None

    tracks: list[EntityTrack] = []
    next_id = 1
    min_hits = int(cfg["min_confirm_hits"])
    high_th = float(cfg["high_score_threshold"])
    low_th = float(cfg["low_score_threshold"])
    init_th = float(cfg["init_score_threshold"])
    stats = defaultdict(float)

    for frame in frames:
        if progress and frame.frame_id % 200 == 0:
            print(f"  tracking frame {frame.frame_id}/{len(frames)}", flush=True)
        active = [track for track in tracks if track.status in ("tentative", "confirmed", "lost")]
        high = [entity for entity in frame.entities if entity.score >= high_th]
        low = [entity for entity in frame.entities if low_th <= entity.score < high_th]
        matched_entity_ids: set[int] = set()
        matched_track_ids: set[str] = set()

        for ti, ei, total, comps in associate(active, high, frame, cfg):
            _update_track(active[ti], high[ei], total, min_hits)
            _accumulate(stats, total, comps)
            matched_entity_ids.add(id(high[ei]))
            matched_track_ids.add(active[ti].track_id)

        remaining = [track for track in active if track.track_id not in matched_track_ids]
        for ti, ei, total, comps in associate(remaining, low, frame, cfg):
            _update_track(remaining[ti], low[ei], total, min_hits)
            _accumulate(stats, total, comps)
            matched_entity_ids.add(id(low[ei]))
            matched_track_ids.add(remaining[ti].track_id)

        pending = [
            entity
            for entity in high + low
            if id(entity) not in matched_entity_ids and entity.score >= init_th
        ]
        for track, entity, total, comps in _revive(tracks, pending, frame, cfg):
            _update_track(track, entity, total, min_hits)
            _accumulate(stats, total, comps)
            matched_entity_ids.add(id(entity))
            matched_track_ids.add(track.track_id)

        for entity in pending:
            if id(entity) in matched_entity_ids:
                continue
            tracks.append(_create_track(next_id, entity, min_hits))
            next_id += 1

        for track in active:
            if track.track_id not in matched_track_ids:
                _mark_missed(track, cfg)

    return tracks, _finish_stats(stats)


def assign_parent_tracks(frames: list[FrameGraph], tracks: list[EntityTrack]):
    from collections import Counter

    votes: dict[str, Counter] = defaultdict(Counter)
    by_id = {track.track_id: track for track in tracks}
    for frame in frames:
        index_to_track = {entity.local_index: entity.track_id for entity in frame.entities}
        name_to_index = {entity.local_name: entity.local_index for entity in frame.entities}
        for entity in frame.entities:
            if not entity.track_id or not entity.parent_local_name:
                continue
            parent_index = name_to_index.get(entity.parent_local_name)
            if parent_index is None:
                continue
            parent_track = index_to_track.get(parent_index)
            if parent_track and parent_track != entity.track_id:
                votes[entity.track_id][parent_track] += 1
    for track_id, counter in votes.items():
        if counter and track_id in by_id:
            by_id[track_id].parent_track_id = counter.most_common(1)[0][0]


def assign_relation_tracks(frames: list[FrameGraph]):
    for frame in frames:
        for relation in frame.relations:
            relation.subject_track_id = frame.entities[relation.subject_index].track_id
            relation.object_track_id = frame.entities[relation.object_index].track_id
