"""验证视频、场景图、查询和导出始终绑定同一素材。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scene_fixtures import scene_workspace
from video_hsg.video_workspace import VideoSceneRegistry


class VideoWorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.workspace = scene_workspace(Path(self.folder.name))
        self.registry = VideoSceneRegistry(self.workspace)

    def tearDown(self):
        self.folder.cleanup()

    def test_all_data_and_preview_follow_video(self):
        graph = self.registry.get("processed")
        pending = self.registry.get("pending")
        self.assertTrue(graph.has_graph)
        self.assertFalse(pending.has_graph)
        self.assertTrue(graph.search("fixture_object", "实体"))
        self.assertEqual(pending.search("fixture_object", "实体"), [])
        graph_payload = json.loads(graph.timeline_json())
        self.assertTrue(graph_payload["nodes"])
        self.assertEqual(graph_payload["video_id"], "processed")
        pending_payload = json.loads(pending.timeline_json())
        self.assertEqual(pending_payload["nodes"], [])
        self.assertEqual(pending_payload["video_id"], "pending")
        view = pending.view(0)
        self.assertEqual(json.loads(view["layered"])["nodes"], [])
        for key in ("timeline", "clip_graph", "video_graph"):
            self.assertIsNone(view[key])
        self.assertEqual(view["entities"], [])
        self.assertEqual(view["relations"], [])
        self.assertIn("pending", view["info"])
        self.assertNotIn("browser.cypher", pending.neo4j_text)
        self.assertIn("browser.cypher", graph.neo4j_text)
        # 实际画面颜色来自各自视频；即使后续查询另一个视频，前一个上下文也不改变。
        red = np.asarray(graph.frame_view(0, show_boxes=False)["frame"]).mean(axis=(0, 1))
        blue = np.asarray(view["frame"]).mean(axis=(0, 1))
        self.assertGreater(red[0], red[2] + 100)
        self.assertGreater(blue[2], blue[0] + 100)
        self.assertTrue(graph.search("fixture_object", "实体"))
        self.assertTrue(pending.video_file(True).endswith("pending.mp4"))

    def test_mismatched_binding_and_frames_are_rejected(self):
        original = self.workspace.video("processed")
        for changes, word in [({"scene_video_sha256": "wrong"}, "指纹"),
                              ({"scene_source_id": "another"}, "编号")]:
            self.workspace.register(Path(original["path"]), {**original, **changes})
            scene = self.registry.get("processed")
            self.assertFalse(scene.has_graph)
            self.assertIn(word, scene.reason)
            self.assertEqual(scene.search("fixture_object", "实体"), [])
        self.workspace.register(Path(original["path"]), original)
        self.assertTrue(self.registry.get("processed").has_graph)
        bundle_path = Path(original["scene_bundle"])
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        bundle["frames"].pop()
        bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
        self.assertFalse(self.registry.get("processed").has_graph)
        self.assertIn("帧数", self.registry.get("processed").reason)

    def test_history_is_not_reused_when_video_content_changes(self):
        original = self.workspace.video("processed")
        self.workspace.save(original, {"summary": "old video", "entities": [], "events": []}, "imported")
        self.assertEqual(len(self.workspace.history("processed")), 1)
        other = self.workspace.video("pending")
        self.workspace.register(Path(other["path"]), original)
        self.assertEqual(self.workspace.history("processed"), [])
        self.assertFalse(self.registry.get("processed").has_graph)


if __name__ == "__main__":
    unittest.main()
