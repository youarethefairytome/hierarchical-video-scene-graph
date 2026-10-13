"""时间关系平滑、事件和固定窗口 Clip。"""

from __future__ import annotations

from collections import Counter, defaultdict

from video_hsg.normalize.labels import DYNAMIC_PREDICATES, TRANSITION_PATTERNS
from video_hsg.schemas import EntityTrack, FrameGraph


def clip_ranges(frame_count: int, window: int, overlap: int) -> list[tuple[int, int]]:
    if frame_count <= 0:
        return []
    step = max(1, window - overlap)
    ranges: list[tuple[int, int]] = []
    start = 0
    while start < frame_count:
        end = min(frame_count - 1, start + window - 1)
        ranges.append((start, end))
        if end >= frame_count - 1:
            break
        start += step
    return ranges


def _collapse_frames(items: list[tuple[int, str]]) -> list[tuple[int, str]]:
    grouped: dict[int, list[str]] = defaultdict(list)
    for frame_id, predicate in items:
        grouped[frame_id].append(predicate)
    collapsed = []
    for frame_id in sorted(grouped):
        predicate = Counter(grouped[frame_id]).most_common(1)[0][0]
        collapsed.append((frame_id, predicate))
    return collapsed


def _clusters(sequence: list[tuple[int, str]], ttl: int) -> list[list[tuple[int, str]]]:
    groups: list[list[tuple[int, str]]] = [[sequence[0]]]
    for item in sequence[1:]:
        if item[0] - groups[-1][-1][0] - 1 <= ttl:
            groups[-1].append(item)
        else:
            groups.append([item])
    return groups


def _smooth_group(group: list[tuple[int, str]], window: int, ratio: float) -> list[dict]:
    frames = [frame_id for frame_id, _ in group]
    predicates = [predicate for _, predicate in group]
    half = max(0, window // 2)
    smoothed: list[str] = []
    for index in range(len(predicates)):
        chunk = predicates[max(0, index - half) : min(len(predicates), index + half + 1)]
        dominant, count = Counter(chunk).most_common(1)[0]
        smoothed.append(dominant if count / len(chunk) >= ratio else predicates[index])

    segments = []
    start = 0
    for index in range(1, len(smoothed) + 1):
        if index == len(smoothed) or smoothed[index] != smoothed[start]:
            label = smoothed[start]
            original = predicates[start:index]
            confidence = sum(predicate == label for predicate in original) / len(original)
            evidence = [frames[k] for k in range(start, index) if predicates[k] == label] or frames[start:index]
            segments.append(
                {
                    "start_frame": frames[start],
                    "end_frame": frames[index - 1],
                    "predicate": label,
                    "confidence": round(confidence, 3),
                    "evidence_frames": evidence,
                }
            )
            start = index
    return segments


def aggregate_relations(frames: list[FrameGraph], tracks: list[EntityTrack], cfg: dict) -> list[dict]:
    temporal_cfg = cfg["temporal_relation"]
    ttl = int(temporal_cfg["ttl_frames"])
    window = int(temporal_cfg["window_size"])
    ratio = float(temporal_cfg["dominant_ratio"])
    labels = {track.track_id: track.canonical_label for track in tracks}
    source_map = {frame.frame_id: frame.source_frame for frame in frames}
    pairs: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)

    for frame in frames:
        for relation in frame.relations:
            subject = relation.subject_track_id
            obj = relation.object_track_id
            if not subject or not obj or subject == obj:
                continue
            pairs[(subject, obj)].append((frame.frame_id, relation.predicate_norm))

    relations: list[dict] = []
    for (subject, obj), items in pairs.items():
        sequence = _collapse_frames(items)
        if not sequence:
            continue
        for group in _clusters(sequence, ttl):
            for segment in _smooth_group(group, window, ratio):
                start_frame = segment["start_frame"]
                end_frame = segment["end_frame"]
                relations.append(
                    {
                        "subject_track_id": subject,
                        "object_track_id": obj,
                        "subject_label": labels.get(subject, ""),
                        "object_label": labels.get(obj, ""),
                        "predicate": segment["predicate"],
                        "start_frame": start_frame,
                        "end_frame": end_frame,
                        "start_source_frame": source_map.get(start_frame, start_frame),
                        "end_source_frame": source_map.get(end_frame, end_frame),
                        "confidence": segment["confidence"],
                        "evidence_frames": segment["evidence_frames"],
                    }
                )
    relations.sort(key=lambda item: (item["start_frame"], item["subject_track_id"], item["predicate"]))
    for index, relation in enumerate(relations, start=1):
        relation["relation_id"] = f"rel_{index:05d}"
    return relations


def _compressed_runs(sequence: list[tuple[int, str]]) -> list[tuple[int, int, str]]:
    start, predicate = sequence[0]
    end = start
    runs: list[tuple[int, int, str]] = []
    for frame_id, current in sequence[1:]:
        if current == predicate:
            end = frame_id
            continue
        runs.append((start, end, predicate))
        start = end = frame_id
        predicate = current
    runs.append((start, end, predicate))
    return runs


def extract_events(frames: list[FrameGraph], tracks: list[EntityTrack], relations: list[dict]) -> list[dict]:
    labels = {track.track_id: track.canonical_label for track in tracks}
    source_map = {frame.frame_id: frame.source_frame for frame in frames}
    events: list[dict] = []
    for relation in relations:
        if relation["predicate"] not in DYNAMIC_PREDICATES:
            continue
        events.append(
            {
                "subject_track_id": relation["subject_track_id"],
                "object_track_id": relation["object_track_id"],
                "subject_label": relation["subject_label"],
                "object_label": relation["object_label"],
                "action": relation["predicate"],
                "start_frame": relation["start_frame"],
                "end_frame": relation["end_frame"],
                "start_source_frame": relation["start_source_frame"],
                "end_source_frame": relation["end_source_frame"],
                "confidence": relation["confidence"],
                "evidence_frames": relation["evidence_frames"],
                "source": "temporal_relation",
            }
        )

    raw_pairs: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
    for frame in frames:
        for relation in frame.relations:
            subject = relation.subject_track_id
            obj = relation.object_track_id
            if not subject or not obj or subject == obj:
                continue
            raw_pairs[(subject, obj)].append((frame.frame_id, relation.predicate_norm))

    seen: set[tuple] = set()
    for (subject, obj), items in raw_pairs.items():
        runs = _compressed_runs(_collapse_frames(items))
        predicates = [predicate for _, _, predicate in runs]
        for pattern, action in TRANSITION_PATTERNS:
            width = len(pattern)
            for index in range(len(predicates) - width + 1):
                if tuple(predicates[index : index + width]) != pattern:
                    continue
                start_frame = runs[index][0]
                end_frame = runs[index + width - 1][1]
                key = (action, subject, obj, start_frame, end_frame)
                if key in seen:
                    continue
                seen.add(key)
                events.append(
                    {
                        "subject_track_id": subject,
                        "object_track_id": obj,
                        "subject_label": labels.get(subject, ""),
                        "object_label": labels.get(obj, ""),
                        "action": action,
                        "start_frame": start_frame,
                        "end_frame": end_frame,
                        "start_source_frame": source_map.get(start_frame, start_frame),
                        "end_source_frame": source_map.get(end_frame, end_frame),
                        "confidence": 0.75,
                        "evidence_frames": [start_frame, end_frame],
                        "source": "transition",
                    }
                )

    events.sort(key=lambda item: (item["start_frame"], item["action"], item["subject_track_id"]))
    for index, event in enumerate(events, start=1):
        event["event_id"] = f"event_{index:05d}"
    return events


def build_clips(
    frame_count: int,
    tracks: list[EntityTrack],
    relations: list[dict],
    events: list[dict],
    source_map: dict[int, int],
    cfg: dict,
) -> list[dict]:
    window = int(cfg["clip"]["sampled_frames_per_clip"])
    overlap = int(cfg["clip"]["overlap"])
    clips = []
    for clip_index, (start, end) in enumerate(clip_ranges(frame_count, window, overlap)):
        members = []
        label_weights: Counter = Counter()
        for track in tracks:
            inside = [obs.frame_id for obs in track.observations if start <= obs.frame_id <= end]
            if not inside:
                continue
            weight = len(inside)
            if track.parent_track_id:
                weight = max(1, weight // 4)
            label_weights[track.canonical_label] += weight
            members.append(track.track_id)
        overlapping = [
            relation
            for relation in relations
            if not (relation["end_frame"] < start or relation["start_frame"] > end)
        ]
        predicate_weights = Counter(relation["predicate"] for relation in overlapping)
        event_count = sum(1 for event in events if not (event["end_frame"] < start or event["start_frame"] > end))
        top_labels = [label for label, _ in label_weights.most_common(6)]
        top_predicates = [predicate for predicate, _ in predicate_weights.most_common(5)]
        summary = "主要实体：" + ("、".join(top_labels) if top_labels else "无")
        summary += "。主要关系：" + ("、".join(top_predicates) if top_predicates else "无")
        clips.append(
            {
                "clip_id": f"clip_{clip_index:03d}",
                "start_frame": start,
                "end_frame": end,
                "start_source_frame": source_map.get(start, start),
                "end_source_frame": source_map.get(end, end),
                "track_ids": members,
                "relation_count": len(overlapping),
                "event_count": event_count,
                "summary": summary,
            }
        )
    return clips
