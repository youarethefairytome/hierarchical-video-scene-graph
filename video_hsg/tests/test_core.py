"""核心流水线测试：几何、跟踪生命周期、时间平滑、真实 JSON 适配。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from video_hsg.config import load_config
from video_hsg.io.reader import load_frames, make_local_names
from video_hsg.normalize.labels import canonical_label, normalize_predicate
from video_hsg.pipeline import build_scene
from video_hsg.query.search import search_bundle
from video_hsg.schemas import EntityTrack, FrameEntity, FrameGraph, FrameRelation
from video_hsg.service import DemoSession
from video_hsg.temporal.build import aggregate_relations, clip_ranges
from video_hsg.tracking.geometry import pairwise_iou
from video_hsg.tracking.tracker import track_frames


def _entity(frame_id: int, label: str, box: list[float], score: float = 0.9) -> FrameEntity:
    entity = FrameEntity(
        frame_id=frame_id,
        local_index=0,
        local_name=label,
        label=label,
        canonical_label=canonical_label(label),
        bbox=box,
        score=score,
    )
    return entity


def _frame(frame_id: int, entities: list[FrameEntity]) -> FrameGraph:
    for index, entity in enumerate(entities):
        entity.local_index = index
        entity.frame_id = frame_id
    return FrameGraph(
        frame_id=frame_id,
        source_frame=frame_id * 10,
        key=str(frame_id),
        image_path="",
        width=1224,
        height=1024,
        entities=entities,
        relations=[],
    )


class LabelAndGeometryTest(unittest.TestCase):
    def test_local_names_and_aliases(self):
        self.assertEqual(make_local_names(["window", "window", "door"]), ["window1", "window2", "door"])
        self.assertEqual(canonical_label("Windows"), "window")
        self.assertEqual(canonical_label("man"), "person")
        self.assertEqual(normalize_predicate("next to"), "near")
        self.assertEqual(normalize_predicate("part of"), "part_of")

    def test_iou(self):
        same = np.array([[0, 0, 10, 10]], dtype=np.float32)
        self.assertAlmostEqual(float(pairwise_iou(same, same)[0, 0]), 1.0, places=5)
        other = np.array([[10, 10, 20, 20]], dtype=np.float32)
        self.assertAlmostEqual(float(pairwise_iou(same, other)[0, 0]), 0.0, places=5)


class TrackerTest(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config()["tracking"]

    def test_same_object_stays_one_track(self):
        frames = []
        for index in range(4):
            box = [100 + index, 80, 200 + index, 240]
            frames.append(_frame(index, [_entity(index, "window", box)]))
        tracks, _stats = track_frames(frames, self.cfg)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(len(tracks[0].observations), 4)
        self.assertEqual(tracks[0].status, "confirmed")
        self.assertTrue(all(entity.track_id == tracks[0].track_id for frame in frames for entity in frame.entities))

    def test_different_labels_do_not_merge(self):
        frames = [
            _frame(
                index,
                [
                    _entity(index, "window", [100, 80, 180, 200]),
                    _entity(index, "door", [400, 80, 480, 220]),
                ],
            )
            for index in range(3)
        ]
        tracks, _stats = track_frames(frames, self.cfg)
        self.assertEqual(len(tracks), 2)
        self.assertEqual({track.canonical_label for track in tracks}, {"window", "door"})

    def test_confirmed_track_survives_a_gap(self):
        present = [True, True, False, True]
        frames = []
        for index, seen in enumerate(present):
            entities = [_entity(index, "building", [10, 10, 400, 500])] if seen else []
            frames.append(_frame(index, entities))
        tracks, _stats = track_frames(frames, self.cfg)
        alive = [track for track in tracks if track.observations]
        self.assertEqual(len(alive), 1)
        self.assertEqual(len(alive[0].observations), 3)

    def test_removed_track_can_revive(self):
        cfg = dict(self.cfg)
        cfg["max_missed_frames"] = 0
        cfg["revive_max_gap"] = 4
        cfg["revive_min_score"] = 0.5
        present = [True, True, False, False, True]
        frames = []
        for index, seen in enumerate(present):
            entities = [_entity(index, "pole", [300, 40, 360, 500])] if seen else []
            frames.append(_frame(index, entities))
        tracks, _stats = track_frames(frames, cfg)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(len(tracks[0].observations), 3)
        self.assertEqual(tracks[0].status, "confirmed")

    def test_tentative_track_does_not_revive(self):
        present = [True, False, False, True]
        frames = [_frame(index, [_entity(index, "car", [20, 400, 180, 520])] if seen else []) for index, seen in enumerate(present)]
        tracks, _stats = track_frames(frames, self.cfg)
        self.assertEqual(len(tracks), 2)


class TemporalTest(unittest.TestCase):
    def test_clip_ranges_cover_every_frame(self):
        for count in (1, 10, 25, 801):
            ranges = clip_ranges(count, 10, 2)
            covered = set()
            for start, end in ranges:
                self.assertGreaterEqual(end, start)
                covered.update(range(start, end + 1))
            self.assertEqual(covered, set(range(count)))

    def test_dominant_predicate_smooths_one_outlier(self):
        tracks = [
            EntityTrack("track_00001", "person", "man", "confirmed", 0, 3, []),
            EntityTrack("track_00002", "bicycle", "bicycle", "confirmed", 0, 3, []),
        ]
        predicates = ["holding", "holding", "near", "holding"]
        frames = []
        for index, predicate in enumerate(predicates):
            relation = FrameRelation(
                frame_id=index,
                subject_index=0,
                object_index=1,
                subject_local_name="man",
                object_local_name="bicycle",
                predicate_raw=predicate,
                predicate_norm=predicate,
                source="test",
                subject_track_id="track_00001",
                object_track_id="track_00002",
            )
            frames.append(
                FrameGraph(index, index, str(index), "", 100, 100, [], [relation])
            )
        config = {"temporal_relation": {"ttl_frames": 2, "window_size": 5, "dominant_ratio": 0.6}}
        relations = aggregate_relations(frames, tracks, config)
        self.assertEqual(len(relations), 1)
        self.assertEqual(relations[0]["predicate"], "holding")
        self.assertEqual(relations[0]["start_frame"], 0)
        self.assertEqual(relations[0]["end_frame"], 3)


class TimelineLayerTest(unittest.TestCase):
    def test_l3_is_hierarchy_layer_not_attribute(self):
        from video_hsg.visualization.timeline_layers import hierarchy_sets, layer_of

        layer2, layer3 = hierarchy_sets(
            {
                "layer1_nodes": ["building1", "door2"],
                "layer2_mapping": {"building1": ["windows1"]},
                "layer3_mapping": {"door2": ["label1", "label2"]},
            }
        )
        self.assertEqual(layer_of("label1", layer2, layer3), 3)
        self.assertEqual(layer_of("windows1", layer2, layer3), 2)
        self.assertEqual(layer_of("building1", layer2, layer3), 1)
        self.assertEqual(layer_of("door2", layer2, layer3), 1)
        from video_hsg.visualization.timeline_layers import parent_links

        pairs = parent_links(
            {
                "layer2_mapping": {"building1": ["windows1"]},
                "layer3_mapping": {"door2": ["label1"]},
            }
        )
        self.assertEqual(pairs, [("building1", "windows1"), ("door2", "label1")])


class LayeredSceneTest(unittest.TestCase):
    def test_frame_has_five_layers(self):
        from video_hsg.visualization.layered import build_layered_scene

        config = load_config()
        frames, _warnings, _mismatches = load_frames(Path(config["paths"]["scene_dir"]), config, max_frames=1)
        frame = frames[0]
        payload = build_layered_scene(
            {
                "frame_id": frame.frame_id,
                "source_frame": frame.source_frame,
                "entities": [
                    {
                        "local_name": entity.local_name,
                        "canonical_label": entity.canonical_label,
                        "score": entity.score,
                        "attribute_text": entity.attribute_text,
                        "parent_local_name": entity.parent_local_name,
                        "track_id": None,
                    }
                    for entity in frame.entities
                ],
                "relations": [
                    {
                        "subject_local_name": relation.subject_local_name,
                        "object_local_name": relation.object_local_name,
                        "predicate": relation.predicate_norm,
                        "subject_track_id": None,
                        "object_track_id": None,
                    }
                    for relation in frame.relations
                ],
            }
        )
        layers = {node["layer"] for node in payload["nodes"]}
        self.assertEqual(layers, {0, 1, 2, 3, 4})
        names = {entity.local_name for entity in frame.entities}
        roots = [entity for entity in frame.entities if not entity.parent_local_name or entity.parent_local_name not in names]
        layer1 = [node for node in payload["nodes"] if node["layer"] == 1]
        layer4 = [node for node in payload["nodes"] if node["layer"] == 4]
        self.assertEqual(len(layer1), len(roots))
        self.assertEqual(len(layer4), len(frame.relations))
        self.assertTrue(any(node["id"] == "scene" for node in payload["nodes"]))


class SearchTest(unittest.TestCase):
    def test_entity_query_does_not_match_every_track(self):
        bundle = {
            "tracks": [
                {
                    "track_id": "track_00001",
                    "canonical_label": "bench",
                    "raw_label": "bench",
                    "start_frame": 0,
                    "end_frame": 2,
                    "start_source_frame": 0,
                    "end_source_frame": 20,
                    "attributes": ["Metal park bench"],
                },
                {
                    "track_id": "track_00002",
                    "canonical_label": "person",
                    "raw_label": "man",
                    "start_frame": 1,
                    "end_frame": 4,
                    "start_source_frame": 10,
                    "end_source_frame": 40,
                    "attributes": ["Person in a red jacket"],
                },
            ],
            "temporal_relations": [],
            "events": [],
        }
        rows = search_bundle(bundle, "person", "实体")
        self.assertEqual([row[6] for row in rows], ["track_00002"])
        rows = search_bundle(bundle, "man", "实体")
        self.assertEqual([row[6] for row in rows], ["track_00002"])
        self.assertEqual(search_bundle(bundle, "building", "实体"), [])
        self.assertEqual(search_bundle(bundle, "window", "实体"), [])


class RealSceneTest(unittest.TestCase):
    def test_reader_aligns_relation_indexes(self):
        config = load_config()
        frames, _warnings, mismatches = load_frames(Path(config["paths"]["scene_dir"]), config, max_frames=5)
        self.assertEqual(len(frames), 5)
        self.assertEqual(mismatches, 0)
        self.assertTrue(any(entity.attribute_text for frame in frames for entity in frame.entities))
        for frame in frames:
            for relation in frame.relations:
                subject = frame.entities[relation.subject_index]
                obj = frame.entities[relation.object_index]
                self.assertEqual(subject.local_name, relation.subject_local_name)
                self.assertEqual(obj.local_name, relation.object_local_name)

    def test_short_pipeline_is_queryable(self):
        config = load_config()
        with tempfile.TemporaryDirectory() as tmp:
            config["paths"]["output_dir"] = tmp
            bundle = build_scene(config, max_frames=8, ablation=True, write=True)
            self.assertTrue((Path(tmp) / "neo4j" / "browser.cypher").exists())
            self.assertTrue((Path(tmp) / "tracks.json").exists())
        self.assertGreater(bundle["summary"]["tracks"], 0)
        self.assertGreater(len(bundle["clips"]), 0)
        label = bundle["summary"]["top_labels"][0][0]
        rows = search_bundle(bundle, label, "实体")
        self.assertTrue(rows)
        self.assertEqual(rows[0][4], "实体")
        view = DemoSession(bundle).view(0, False, [])
        self.assertEqual(view["frame_id"], 0)
        self.assertIsNotNone(view["frame"])
        self.assertIn("video_graph", bundle)


if __name__ == "__main__":
    unittest.main()
