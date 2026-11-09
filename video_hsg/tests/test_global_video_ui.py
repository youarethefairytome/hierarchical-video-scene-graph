"""实际 Gradio 全页面切换回归，覆盖图清除、历史隔离、播放器及查询。"""
from __future__ import annotations

import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path

from gradio_client import Client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "app"))

from scene_fixtures import scene_workspace
from gradio_app import build_demo


class GlobalVideoUITest(unittest.TestCase):
    def test_switch_updates_every_tab_and_clears_previous_data(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = scene_workspace(Path(folder))
            saved = workspace.save(workspace.video("processed"),
                                   {"summary": "processed video summary", "entities": [], "events": []}, "imported")
            demo = build_demo(workspace)
            selectors = [c for c in demo.config["components"] if c["props"].get("elem_id") == "active-video"]
            self.assertEqual(len(selectors), 1)
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            try:
                demo.launch(server_name="127.0.0.1", server_port=port, prevent_thread_lock=True,
                            quiet=True, inbrowser=False)
                client = Client(f"http://127.0.0.1:{port}", verbose=False)
                dependency = next(d for d in demo.config["dependencies"] if d.get("api_name") == "select_scene")
                components = {c["id"]: c for c in demo.config["components"]}
                visible_outputs = [components[i] for i in dependency["outputs"] if not components[i].get("skip_api")]

                def switch(video_id):
                    values = client.predict(video_id, api_name="/select_scene")
                    self.assertEqual(len(values), len(visible_outputs))
                    return list(zip(visible_outputs, values))

                def value(outputs, label):
                    return next(v for c, v in outputs if c["props"].get("label") == label)

                def graphs(outputs):
                    return [json.loads(v) for c, v in outputs if c["type"] == "html" and isinstance(v, str) and v.startswith('{"')]

                processed = switch("processed")
                self.assertEqual(value(processed, "历史记录")["value"], saved["id"])
                self.assertTrue(all(g["video_id"] == "processed" and g["nodes"] for g in graphs(processed)))
                videos = [v for c, v in processed if c["type"] == "video"]
                self.assertTrue(all("processed.mp4" in str(v) for v in videos))
                self.assertTrue(client.predict("processed", "fixture_object", "实体", api_name="/do_search")["data"])

                pending = switch("pending")
                self.assertIsNone(value(pending, "历史记录")["value"])
                self.assertEqual(value(pending, "查询结果（点击一行跳到起始帧）")["data"], [])
                self.assertEqual(value(pending, "当前视频的关联消融")["data"], [])
                self.assertFalse(value(pending, "显示当前视频的识别框")["interactive"])
                self.assertEqual(value(pending, "采样 / 预览帧")["value"], 0)
                self.assertFalse(value(pending, "播放"))
                self.assertTrue(all(g["video_id"] == "pending" and not g["nodes"] for g in graphs(pending)))
                self.assertTrue(all(v is None for c, v in pending if c["props"].get("label") in
                                    ("当前视频的轨迹时间线", "ClipGraph", "VideoGraph")))
                self.assertTrue(all("pending.mp4" in str(v) for c, v in pending if c["type"] == "video"))
                self.assertEqual(client.predict("pending", "fixture_object", "实体", api_name="/do_search")["data"], [])
                refreshed = client.predict("pending", 2, False, True, False, api_name="/refresh")
                self.assertIn("pending", refreshed[0])
                self.assertEqual(json.loads(refreshed[2])["nodes"], [])
                self.assertIsNone(refreshed[3])

                # 第二个浏览器会话查图不改变第一个请求所依赖的视频来源。
                second = Client(f"http://127.0.0.1:{port}", verbose=False)
                self.assertTrue(second.predict("processed", "fixture_object", "实体", api_name="/do_search")["data"])
                self.assertEqual(client.predict("pending", "fixture_object", "实体", api_name="/do_search")["data"], [])
                restored = switch("processed")
                self.assertEqual(value(restored, "历史记录")["value"], saved["id"])
                self.assertTrue(all(g["nodes"] for g in graphs(restored)))
            finally:
                demo.close()


if __name__ == "__main__":
    unittest.main()
