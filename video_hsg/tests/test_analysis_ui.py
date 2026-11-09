"""通过实际 Gradio HTTP 回调验证视频切换、导入、历史回放和无 Key 提示。"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

import cv2
import gradio as gr
import numpy as np
from gradio_client import Client, handle_file

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "app"))

from analysis_tab import build_analysis_tab
from scene_fixtures import scene_workspace
from video_hsg.analysis import AnalysisWorkspace, ModelCatalogError


class AnalysisUITest(unittest.TestCase):
    def test_video_import_history_and_empty_api(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            media = root / "fixture.mp4"
            writer = cv2.VideoWriter(str(media), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
            for value in range(12):
                writer.write(np.full((48, 64, 3), value * 10, dtype=np.uint8))
            writer.release()
            workspace = scene_workspace(root)
            for video_id in ("first", "second"):
                workspace.register(Path(workspace.video("processed")["path"]), {**workspace.video("processed"), "id": video_id, "title": video_id})
            with gr.Blocks() as demo:
                build_analysis_tab(workspace)
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            try:
                demo.launch(server_name="127.0.0.1", server_port=port, prevent_thread_lock=True,
                            quiet=True, show_error=True, inbrowser=False)
                client = Client(f"http://127.0.0.1:{port}", verbose=False)
                with patch("analysis_tab.list_models", return_value=["text-a", "text-b"]) as catalog:
                    models = client.predict("https://fixture.invalid/v1", "fixture-key", "", api_name="/fetch_models")
                    self.assertEqual(models[0]["value"], "text-a")
                    self.assertEqual(models[0]["choices"], [["text-a", "text-a"], ["text-b", "text-b"]])
                    catalog.assert_called_once_with("https://fixture.invalid/v1", "fixture-key")
                with patch("analysis_tab.list_models", return_value=["text-a"]) as catalog, patch.dict("os.environ", {"VIDEO_LLM_API_KEY": "env-key"}):
                    models = client.predict("https://fixture.invalid/v1/chat/completions", "  ", "manual-model", api_name="/fetch_models")
                    self.assertEqual(models[0]["value"], "manual-model")
                    catalog.assert_called_once_with("https://fixture.invalid/v1/chat/completions", "env-key")
                denied = ModelCatalogError("访问失败（HTTP 403）", detail='<script>alert("bad")</script>',
                                           suggestion="检查网关规则", url="https://fixture.invalid/v1/models")
                with patch("analysis_tab.list_models", side_effect=denied):
                    failed = client.predict("https://fixture.invalid/v1", "test-key", "manual-model", api_name="/fetch_models")
                    self.assertNotIn("choices", failed[0])
                    self.assertNotIn("value", failed[0])
                    self.assertIn("HTTP 403", failed[1])
                    self.assertIn("&lt;script&gt;", failed[1])
                    self.assertNotIn("<script>", failed[1])
                    self.assertIn("/v1/models", failed[1])
                self.assertEqual(workspace.history("first"), [])
                selection = client.predict("second", api_name="/select_video")
                self.assertEqual(selection[2]["choices"], [])
                result = {"entities": [], "events": [], "summary": "界面测试结果，不是模型推断。", "limitations": "仅测试"}
                payload = root / "result.json"
                payload.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
                imported = client.predict("second", handle_file(payload), api_name="/import_result")
                self.assertEqual(imported[0], result["summary"])
                self.assertIn("外部导入", imported[6])
                exported = json.loads(Path(imported[5]).read_text(encoding="utf-8"))
                self.assertEqual(exported["origin"], "imported")
                self.assertEqual(len(workspace.history("second")), 1)
                self.assertEqual(len(workspace.history("first")), 0)
                other = client.predict("first", api_name="/select_video")
                self.assertEqual(other[6], "")
                reloaded = client.predict("second", api_name="/select_video")
                self.assertEqual(reloaded[6], result["summary"])
                run_id = exported["id"]
                historical = client.predict(run_id, "second", api_name="/load_history")
                self.assertEqual(historical[0], result["summary"])
                self.assertTrue(Path(client.predict("second", 0.2, api_name="/preview")).exists())
                failed = client.predict("second", "", "", "", "测试", 4, 1024, api_name="/lambda")
                self.assertIn("尚未配置", failed[-1])
                self.assertIn("分析未完成", failed[-1])
                self.assertEqual(failed[0], {"__type__": "update"})
                with patch.dict(os.environ):
                    saved = client.predict("https://saved.invalid/v1", "ui-test-secret", "saved-model", api_name="/save_connection")
                    self.assertEqual(saved[0]["value"], "")
                    self.assertNotIn("ui-test-secret", json.dumps(saved))
                    self.assertIn("VIDEO_LLM_API_KEY", (root / ".env").read_text(encoding="utf-8"))
                    os.environ.pop("VIDEO_LLM_BASE_URL", None)
                    os.environ.pop("VIDEO_LLM_API_KEY", None)
                    os.environ.pop("VIDEO_LLM_MODEL", None)
                    AnalysisWorkspace(root)  # 模拟服务重新创建，自动读取保存的 .env。
                    self.assertEqual(os.environ["VIDEO_LLM_API_KEY"], "ui-test-secret")
                    self.assertEqual(client.predict(api_name="/configured_endpoint"), "https://saved.invalid/v1")
                    self.assertEqual(client.predict(api_name="/configured_model"), "saved-model")
                    with patch("analysis_tab.list_models", return_value=["saved-model"]) as catalog:
                        client.predict("https://saved.invalid/v1", "", "saved-model", api_name="/fetch_models")
                        catalog.assert_called_once_with("https://saved.invalid/v1", "ui-test-secret")
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/config") as response:
                        self.assertNotIn("ui-test-secret", response.read().decode("utf-8"))
            finally:
                demo.close()


if __name__ == "__main__":
    unittest.main()
