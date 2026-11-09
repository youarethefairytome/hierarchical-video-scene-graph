"""隔离测试素材；颜色块与场景图均为人工测试夹具，不写入演示资料库。"""
import json
from pathlib import Path

import cv2
import numpy as np

from video_hsg.analysis import AnalysisWorkspace, file_hash


def scene_workspace(root: Path):
    workspace = AnalysisWorkspace(root)
    for video_id, color in [("pending", (210, 40, 20)), ("processed", (20, 40, 210))]:
        path = root / (video_id + ".mp4")
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (96, 80))
        for _ in range(12):
            writer.write(np.full((80, 96, 3), color, dtype=np.uint8))
        writer.release()
        metadata = {"id": video_id, "title": video_id, "camera": "fixed", "source": "test", "description": "fixture"}
        if video_id == "processed":
            folder = root / "processed" / "fixture"
            folder.mkdir(parents=True)
            bundle = {
                "meta": {"scene_id": "fixture", "scene_dir": str(root / "raw_fixture")},
                "frames": [{"frame_id": i, "source_frame": i, "key": str(i), "image_path": "", "width": 96, "height": 80,
                            "entities": [{"local_index": 0, "local_name": "fixture_object", "canonical_label": "fixture_object",
                                          "score": 0.9, "bbox": [10, 10, 30, 40], "track_id": "track_fixture",
                                          "parent_local_name": None, "attribute_text": "test object"}], "relations": []}
                           for i in range(12)],
                "tracks": [{"track_id": "track_fixture", "canonical_label": "fixture_object", "raw_label": "fixture_object",
                            "attributes": [], "frame_ids": list(range(12)), "observation_count": 12,
                            "start_frame": 0, "end_frame": 11, "start_source_frame": 0, "end_source_frame": 11}],
                "temporal_relations": [], "events": [],
                "clips": [{"clip_id": "clip_fixture", "start_frame": 0, "end_frame": 11, "start_source_frame": 0,
                           "end_source_frame": 11, "track_ids": ["track_fixture"], "summary": "fixture clip"}],
                "summary": {"frame_count": 12, "tracks": 1, "event_count": 0, "clip_count": 1,
                            "top_labels": [["fixture_object", 12]], "comparison": "fixture comparison"},
                "ablation": [{"method": "fixture method", "tracks": 1}],
            }
            bundle_path = folder / "scene_bundle.json"
            bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
            exports = folder / "neo4j"
            exports.mkdir()
            (exports / "browser.cypher").write_text("// fixture export", encoding="utf-8")
            metadata.update(scene_bundle=str(bundle_path), scene_video_sha256=file_hash(path),
                            scene_source_id="fixture", graph_frame_mapping="sampled_video")
        workspace.register(path, metadata)
    return workspace
