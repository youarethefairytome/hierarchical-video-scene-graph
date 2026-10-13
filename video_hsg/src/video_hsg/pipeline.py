"""从单帧 HSGG 构建 Track、时间关系、Clip、VideoGraph 和查询数据。"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from video_hsg.graph.export_neo4j import export_neo4j
from video_hsg.io.reader import load_frames
from video_hsg.schemas import EntityTrack, FrameGraph
from video_hsg.temporal.build import aggregate_relations, build_clips, extract_events
from video_hsg.tracking.tracker import assign_parent_tracks, assign_relation_tracks, track_frames
from video_hsg.visualization.render import render_frame, render_frame_graph, render_timeline

WEIGHT_KEYS = (
    "weight_iou",
    "weight_center",
    "weight_size",
    "weight_label",
    "weight_attribute",
    "weight_hierarchy",
    "weight_relation",
)

ABLATION_VARIANTS = (
    (
        "A_IoU",
        {
            "weight_iou": 1.0,
            "weight_center": 0.0,
            "weight_size": 0.0,
            "weight_label": 0.0,
            "weight_attribute": 0.0,
            "weight_hierarchy": 0.0,
            "weight_relation": 0.0,
        },
    ),
    (
        "B_几何",
        {
            "weight_iou": 0.50,
            "weight_center": 0.30,
            "weight_size": 0.20,
            "weight_label": 0.0,
            "weight_attribute": 0.0,
            "weight_hierarchy": 0.0,
            "weight_relation": 0.0,
        },
    ),
    (
        "C_几何+类别",
        {
            "weight_iou": 0.35,
            "weight_center": 0.25,
            "weight_size": 0.15,
            "weight_label": 0.25,
            "weight_attribute": 0.0,
            "weight_hierarchy": 0.0,
            "weight_relation": 0.0,
        },
    ),
    ("本文_层次上下文", None),
)


def _round_box(box: list[float]) -> list[float]:
    return [round(float(value), 2) for value in box]


def _metrics(tracks: list[EntityTrack], match_stats: dict) -> dict:
    lengths = [len(track.observations) for track in tracks] or [0]
    singleton = sum(1 for length in lengths if length <= 1)
    confirmed = sum(1 for track in tracks if track.hits >= 2)
    ordered = sorted(lengths)
    mid = ordered[len(ordered) // 2]
    return {
        "tracks": len(tracks),
        "confirmed": confirmed,
        "mean_length": round(sum(lengths) / len(lengths), 2),
        "median_length": mid,
        "max_length": max(lengths),
        "singleton_ratio": round(singleton / max(len(tracks), 1), 3),
        "observations": sum(lengths),
        **match_stats,
    }


def _comparison_text(rows: list[dict]) -> str:
    if len(rows) < 2:
        return "未运行消融。"
    base = rows[0]
    ours = rows[-1]
    text = (
        f"没有人工标注时，用轨迹连续性做代理指标。"
        f"IoU 基线平均长度 {base['mean_length']}、碎片比例 {base['singleton_ratio']}；"
        f"本文方法平均长度 {ours['mean_length']}、碎片比例 {ours['singleton_ratio']}。"
        f"接受匹配的平均属性相似度：基线 {base['mean_attribute']}，本文 {ours['mean_attribute']}；"
        f"层次相似度：基线 {base['mean_hierarchy']}，本文 {ours['mean_hierarchy']}；"
        f"关系上下文：基线 {base['mean_relation']}，本文 {ours['mean_relation']}。"
    )
    if ours["mean_length"] >= base["mean_length"] and ours["singleton_ratio"] <= base["singleton_ratio"]:
        text += "本文方法的轨迹更长、碎片更少。"
    elif (ours["mean_attribute"] + ours["mean_hierarchy"] + ours["mean_relation"]) > (
        base["mean_attribute"] + base["mean_hierarchy"] + base["mean_relation"]
    ):
        text += "本文方法接受的匹配在属性、层次或关系上下文上更一致。长度需要结合场景解读。"
    else:
        text += "这组代理指标没有显示本文方法全面优于 IoU，权重仍然放在配置文件里，可以继续调。"
    return text


def _serialize_track(track: EntityTrack, source_map: dict[int, int]) -> dict:
    return {
        "track_id": track.track_id,
        "canonical_label": track.canonical_label,
        "raw_label": track.raw_label,
        "status": track.status,
        "start_frame": track.start_frame,
        "end_frame": track.end_frame,
        "start_source_frame": source_map.get(track.start_frame, track.start_frame),
        "end_source_frame": source_map.get(track.end_frame, track.end_frame),
        "hits": track.hits,
        "observation_count": len(track.observations),
        "parent_track_id": track.parent_track_id,
        "attributes": list(track.attributes),
        "frame_ids": [obs.frame_id for obs in track.observations],
    }


def _serialize_frame(frame: FrameGraph) -> dict:
    return {
        "frame_id": frame.frame_id,
        "source_frame": frame.source_frame,
        "key": frame.key,
        "image_path": frame.image_path,
        "width": frame.width,
        "height": frame.height,
        "entities": [
            {
                "local_index": entity.local_index,
                "local_name": entity.local_name,
                "label": entity.label,
                "canonical_label": entity.canonical_label,
                "bbox": _round_box(entity.bbox),
                "score": round(float(entity.score), 4),
                "attribute_text": entity.attribute_text,
                "parent_local_name": entity.parent_local_name,
                "child_local_names": entity.child_local_names,
                "track_id": entity.track_id,
            }
            for entity in frame.entities
        ],
        "relations": [
            {
                "subject_index": relation.subject_index,
                "object_index": relation.object_index,
                "subject_local_name": relation.subject_local_name,
                "object_local_name": relation.object_local_name,
                "subject_track_id": relation.subject_track_id,
                "object_track_id": relation.object_track_id,
                "predicate_raw": relation.predicate_raw,
                "predicate": relation.predicate_norm,
                "source": relation.source,
            }
            for relation in frame.relations
        ],
    }


def _run_ablation(frames, tracking_cfg: dict) -> tuple[list[EntityTrack], dict, list[dict]]:
    rows = []
    ours_tracks: list[EntityTrack] | None = None
    ours_stats: dict | None = None
    for name, weights in ABLATION_VARIANTS:
        variant = dict(tracking_cfg)
        if weights is not None:
            variant.update(weights)
        print(f"ablation {name}", flush=True)
        tracks, stats = track_frames(frames, variant, progress=True)
        metrics = _metrics(tracks, stats)
        metrics["method"] = name
        for key in WEIGHT_KEYS:
            metrics[key] = variant[key]
        rows.append(metrics)
        if weights is None:
            ours_tracks, ours_stats = tracks, stats
    assert ours_tracks is not None and ours_stats is not None
    return ours_tracks, ours_stats, rows


def _dump(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)


def _write_previews(bundle: dict, output_dir: Path):
    frames = bundle["frames"]
    if not frames:
        return
    busiest = max(frames, key=lambda frame: sum(1 for entity in frame["entities"] if not entity.get("parent_local_name")))
    render_frame(busiest, show_parts=False, highlight=set()).save(output_dir / "preview_frame.png")
    render_frame_graph(busiest, False, set()).save(output_dir / "preview_graph.png")
    render_timeline(bundle["tracks"], busiest["frame_id"], bundle["clips"][0] if bundle["clips"] else None, set(), len(frames)).save(
        output_dir / "preview_timeline.png"
    )


def _configure_stdio():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def build_scene(config: dict, max_frames: int | None = None, ablation: bool = True, write: bool = True) -> dict:
    _configure_stdio()
    scene_dir = Path(config["paths"]["scene_dir"])
    output_dir = Path(config["paths"]["output_dir"])
    print(f"loading {scene_dir}", flush=True)
    frames, warnings, mismatches = load_frames(scene_dir, config, max_frames=max_frames)
    print(f"frames {len(frames)}", flush=True)

    if ablation:
        tracks, match_stats, ablation_rows = _run_ablation(frames, config["tracking"])
    else:
        tracks, match_stats = track_frames(frames, config["tracking"], progress=True)
        ablation_rows = []
    assign_parent_tracks(frames, tracks)
    assign_relation_tracks(frames)

    print("temporal aggregation", flush=True)
    relations = aggregate_relations(frames, tracks, config)
    events = extract_events(frames, tracks, relations)
    source_map = {frame.frame_id: frame.source_frame for frame in frames}
    clips = build_clips(len(frames), tracks, relations, events, source_map, config)

    label_weights: Counter = Counter()
    for track in tracks:
        weight = len(track.observations)
        if track.parent_track_id:
            weight = max(1, weight // 4)
        label_weights[track.canonical_label] += weight
    predicate_weights = Counter(relation["predicate"] for relation in relations)
    metrics = _metrics(tracks, match_stats)
    summary = {
        **metrics,
        "frame_count": len(frames),
        "relation_count": len(relations),
        "event_count": len(events),
        "transition_events": sum(1 for event in events if event["source"] == "transition"),
        "clip_count": len(clips),
        "top_labels": label_weights.most_common(12),
        "top_predicates": predicate_weights.most_common(12),
        "warning_count": len(warnings),
        "warnings": warnings[:20],
        "relation_name_mismatches": mismatches,
        "comparison": _comparison_text(ablation_rows),
    }
    video_graph = {
        "scene_id": scene_dir.name,
        "track_count": len(tracks),
        "clip_count": len(clips),
        "relation_count": len(relations),
        "event_count": len(events),
        "clips": [
            {
                "clip_id": clip["clip_id"],
                "start_frame": clip["start_frame"],
                "end_frame": clip["end_frame"],
                "summary": clip["summary"],
            }
            for clip in clips
        ],
        "part_of": [
            {"child_track_id": track.track_id, "parent_track_id": track.parent_track_id}
            for track in tracks
            if track.parent_track_id
        ],
    }
    bundle = {
        "meta": {
            "scene_id": scene_dir.name,
            "scene_dir": str(scene_dir),
            "frame_count": len(frames),
            "built_at": datetime.now().isoformat(timespec="seconds"),
            "method": "HSGG 单帧层次图 + 几何/语义/层次/关系上下文关联 + 时间一致性聚合",
        },
        "summary": summary,
        "ablation": ablation_rows,
        "frames": [_serialize_frame(frame) for frame in frames],
        "tracks": [_serialize_track(track, source_map) for track in tracks],
        "temporal_relations": relations,
        "events": events,
        "clips": clips,
        "video_graph": video_graph,
    }
    if write:
        print(f"writing {output_dir}", flush=True)
        _dump(output_dir / "scene_bundle.json", bundle)
        _dump(output_dir / "summary.json", {"meta": bundle["meta"], "summary": summary})
        _dump(output_dir / "ablation.json", ablation_rows)
        _dump(output_dir / "frames.json", bundle["frames"])
        _dump(output_dir / "tracks.json", bundle["tracks"])
        _dump(output_dir / "temporal_relations.json", relations)
        _dump(output_dir / "clips.json", clips)
        _dump(output_dir / "events.json", events)
        _dump(output_dir / "video_graph.json", video_graph)
        export_neo4j(bundle, output_dir / "neo4j", config["export"])
        _write_previews(bundle, output_dir)
        print(summary["comparison"], flush=True)
        print(
            f"done tracks={summary['tracks']} relations={summary['relation_count']} events={summary['event_count']}",
            flush=True,
        )
    return bundle
