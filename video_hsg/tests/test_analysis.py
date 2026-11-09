"""离线 HTTP 集成测试：真实采样/消息格式、缓存隔离、持久化和错误留档。"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from video_hsg.analysis import AnalysisWorkspace, DEFAULT_PROMPT, endpoint_url, parse_result, validate_result
from scene_fixtures import scene_workspace

RESULT = {"entities": [{"id": "E1", "name": "测试物体", "category": "物体", "description": "测试证据",
                        "evidence_seconds": [0.0], "graph_node_ids": ["track_fixture"]}],
          "events": [{"start_seconds": 0.0, "end_seconds": 0.2, "entity_ids": ["E1"], "description": "可见变化", "graph_evidence": ["track_fixture"]}],
          "summary": "离线接口测试输出，非真实视频推断。", "limitations": "仅测试用"}


class AnalysisTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.media = self.root / "test.mp4"
        writer = cv2.VideoWriter(str(self.media), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
        for index in range(12):
            writer.write(np.full((48, 64, 3), index * 10, dtype=np.uint8))
        writer.release()
        self.workspace = scene_workspace(self.root)
        self.metadata = self.workspace.video("processed")
        self.workspace.register(Path(self.metadata["path"]), {**self.metadata, "id": "test", "title": "测试视频"})
        self.calls = []
        self.response_text = json.dumps(RESULT, ensure_ascii=False)
        self.status = 200
        self.finish_reason = "stop"
        case = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                case.calls.append((payload, self.headers.get("Authorization")))
                self.send_response(case.status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                message = {"content": case.response_text}
                if "tools" in payload and not any(m["role"] == "tool" for m in payload["messages"]):
                    message = {"content": None, "tool_calls": [{"id": "call_search", "type": "function",
                        "function": {"name": "search_graph", "arguments": json.dumps({"query": "fixture_object", "kind": "entity"})}},
                        {"id": "call_node", "type": "function", "function": {"name": "get_node", "arguments": json.dumps({"node_id": "track_fixture"})}}]}
                body = {"choices": [{"finish_reason": case.finish_reason, "message": message}], "usage": {"total_tokens": 99}}
                self.wfile.write(json.dumps(body).encode())

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temporary.cleanup()

    def analyze(self, **changes):
        params = dict(video_id="test", endpoint=self.url, key="test-secret-not-to-store", model="test-text",
                      prompt=DEFAULT_PROMPT, search_rounds=1, max_tokens=1024)
        params.update(changes)
        return self.workspace.analyze(**params)

    def test_request_cache_and_restart_without_key(self):
        record, cached = self.analyze()
        self.assertFalse(cached)
        payload, header = self.calls[0]
        self.assertEqual(header, "Bearer test-secret-not-to-store")
        content = payload["messages"][1]["content"]
        self.assertIsInstance(content, str)
        self.assertNotIn("image_url", json.dumps(payload))
        self.assertNotIn("base64", json.dumps(self.calls))
        self.assertEqual(len(record["evidence"]), 3)
        self.assertEqual(record["evidence"][1]["tool"], "search_graph")
        self.assertEqual(record["evidence"][2]["result"]["node_id"], "track_fixture")
        self.assertEqual(record["usage"]["total_tokens"], 198)
        self.workspace = AnalysisWorkspace(self.root)
        repeated, cached = self.analyze(key="")
        self.assertTrue(cached)
        self.assertEqual(repeated["id"], record["id"])
        self.assertEqual(len(self.calls), 2)
        exported = Path(self.workspace.export(record["id"])).read_text(encoding="utf-8")
        self.assertNotIn("test-secret-not-to-store", exported)
        self.assertNotIn(b"test-secret-not-to-store", self.workspace.database.read_bytes())
        for raw in (self.workspace.folder / "raw_outputs").glob("*.json"):
            self.assertNotIn("test-secret-not-to-store", raw.read_text(encoding="utf-8"))

    def test_parameter_and_video_isolation_and_force(self):
        self.analyze()
        for params in ({"prompt": "不同问题"}, {"model": "another"}, {"search_rounds": 2},
                       {"max_tokens": 2048}, {"endpoint": self.url + "/other"}, {"force": True}):
            _, cached = self.analyze(**params)
            self.assertFalse(cached)
        other = self.root / "other.mp4"
        writer = cv2.VideoWriter(str(other), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
        for _ in range(12):
            writer.write(np.full((48, 64, 3), 255, dtype=np.uint8))
        writer.release()
        self.workspace.register(other, {**self.metadata, "id": "other", "title": "other", "scene_video_sha256": __import__("video_hsg.analysis", fromlist=["file_hash"]).file_hash(other)})
        self.analyze(video_id="other")
        self.assertEqual(len(self.calls), 16)
        self.assertEqual(len(self.workspace.history("test")), 7)
        self.assertEqual(len(self.workspace.history("other")), 1)

    def test_concurrent_clicks_only_send_once(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            records = list(pool.map(lambda _: self.analyze(), range(2)))
        self.assertEqual(len(self.calls), 2)  # 一次图查询响应 + 一次最终结果；并发点击复用整次分析。
        self.assertEqual(records[0][0]["id"], records[1][0]["id"])

    def test_import_export_and_no_false_api_cache(self):
        original, _ = self.analyze()
        path = self.workspace.export(original["id"])
        imported = self.workspace.import_result("test", path)
        self.assertEqual(imported["origin"], "imported")
        self.assertEqual(imported["result"], RESULT)
        with self.assertRaisesRegex(ValueError, "尚未配置"):
            self.analyze(model="different", key="")
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data["video"]["sha256"] = "wrong"
        Path(path).write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "指纹"):
            self.workspace.import_result("test", path)

    def test_invalid_paid_output_is_saved_without_retry(self):
        self.response_text = "not JSON: paid response"
        with self.assertRaisesRegex(ValueError, "原始输出已保存"):
            self.analyze()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.workspace.history("test"), [])
        files = list((self.workspace.folder / "raw_outputs").glob("*.json"))
        self.assertEqual(len(files), 1)
        self.assertIn(self.response_text, files[0].read_text(encoding="utf-8"))

    def test_truncated_and_http_errors_no_retry(self):
        self.finish_reason = "length"
        with self.assertRaisesRegex(ValueError, "截断"):
            self.analyze()
        self.assertEqual(len(list((self.workspace.folder / "raw_outputs").glob("*.json"))), 1)
        self.status = 401
        with self.assertRaisesRegex(ValueError, "HTTP 401"):
            self.analyze()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.workspace.history("test"), [])

    def test_schema_and_endpoint_validation(self):
        self.assertEqual(endpoint_url(self.url), self.url + "/chat/completions")
        self.assertEqual(endpoint_url(self.url + "/chat/completions"), self.url + "/chat/completions")
        with self.assertRaises(ValueError):
            endpoint_url("https://host/v1?key=secret")
        for change in ({"summary": ""}, {"entities": "wrong"}, {"events": [{"start_seconds": float("nan")}]}):
            with self.assertRaises(ValueError):
                validate_result({**RESULT, **change}, 1.2)

    def test_missing_graph_blocks_requests_and_changed_graph_invalidates_cache(self):
        with self.assertRaisesRegex(ValueError, "场景图"):
            self.analyze(video_id="pending")
        self.assertEqual(self.calls, [])
        first, _ = self.analyze()
        path = Path(self.metadata["scene_bundle"])
        bundle = json.loads(path.read_text(encoding="utf-8"))
        bundle["tracks"][0]["attributes"] = ["updated graph evidence"]
        path.write_text(json.dumps(bundle), encoding="utf-8")
        second, cached = self.analyze()
        self.assertFalse(cached)
        self.assertNotEqual(first["request"]["graph_sha256"], second["request"]["graph_sha256"])
        self.assertEqual(len(self.calls), 4)

    def test_graph_tools_scope_times_and_unknown_citations(self):
        from video_hsg.graph_analysis import GraphTools
        from video_hsg.video_workspace import VideoSceneRegistry
        graph = GraphTools(VideoSceneRegistry(self.workspace).get("test"))
        frame = graph.execute("get_frame", {"frame_id": 2})
        self.assertEqual(frame["seconds"], .2)
        self.assertEqual(frame["node_id"], "frame:2")
        self.assertNotIn("image_path", json.dumps(frame))
        with self.assertRaises(ValueError):
            graph.execute("get_node", {"node_id": "another_video/track_fixture"})
        with self.assertRaises(ValueError):
            graph.execute("read_file", {"path": "secret"})
        invalid = json.loads(json.dumps(RESULT))
        invalid["entities"][0]["graph_node_ids"] = ["nonexistent_track"]
        self.response_text = json.dumps(invalid)
        with self.assertRaisesRegex(ValueError, "节点"):
            self.analyze()
        self.assertEqual(self.workspace.history("test"), [])
        self.assertEqual(len(self.calls), 2)

    def test_model_can_search_then_inspect_returned_node_before_final_answer(self):
        sent = []
        def send(endpoint, key, payload):
            sent.append(json.loads(json.dumps(payload)))
            if len(sent) == 1:
                function = {"name": "search_graph", "arguments": json.dumps({"query": "fixture_object", "kind": "entity"})}
            elif len(sent) == 2:
                self.assertEqual(payload["messages"][-2]["reasoning_content"], "private fixture reasoning")
                evidence = json.loads(payload["messages"][-1]["content"])
                node_id = evidence["nodes"][0]["node_id"]
                function = {"name": "get_node", "arguments": json.dumps({"node_id": node_id})}
            else:
                self.assertNotIn("tools", payload)
                self.assertNotIn("tool_choice", payload)
                self.assertEqual(payload["response_format"], {"type": "json_object"})
                self.assertIn("track_fixture", payload["messages"][-1]["content"])
                return {"choices": [{"message": {"content": json.dumps(RESULT)}}]}
            return {"choices": [{"message": {"content": None, "reasoning_content": "private fixture reasoning", "tool_calls": [{"id": f"call_{len(sent)}",
                    "type": "function", "function": function}]}}]}
        with patch("video_hsg.analysis.request_analysis", side_effect=send):
            record, cached = self.analyze(search_rounds=2)
            self.assertFalse(cached)
            self.assertEqual(len(sent), 3)
            self.assertEqual([e["tool"] for e in record["evidence"]], ["graph_overview", "search_graph", "get_node"])
            _, cached = self.analyze(search_rounds=2, key="")
            self.assertTrue(cached)
            self.assertEqual(len(sent), 3)

    def test_json_wrappers_are_supported_but_tool_markup_and_ambiguous_objects_are_rejected(self):
        text = json.dumps(RESULT, ensure_ascii=False)
        for wrapped in (text, "\ufeff" + text, "```json\n" + text + "\n```", "结果如下：\n" + text + "\n结束。"):
            self.assertEqual(parse_result(wrapped), RESULT)
        other = {**RESULT, "summary": "another result"}
        for invalid in (text[:-4], text + json.dumps(other), '<｜｜DSML｜｜tool_calls>{"query":"golf"}</｜｜DSML｜｜tool_calls>'):
            with self.assertRaises(ValueError):
                parse_result(invalid)

    def test_final_tool_markup_failure_can_resume_saved_evidence_in_one_call(self):
        self.response_text = '<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="search_graph"></｜｜DSML｜｜invoke></｜｜DSML｜｜tool_calls>'
        with self.assertRaisesRegex(ValueError, "工具调用文本"):
            self.analyze()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.workspace.history("test"), [])
        source = next((self.workspace.folder / "raw_outputs").glob("*.json"))
        self.response_text = json.dumps(RESULT)
        record, cached = self.analyze(max_tokens=2048)
        self.assertFalse(cached)
        self.assertEqual(len(self.calls), 3)
        final_payload = self.calls[-1][0]
        self.assertNotIn("tools", final_payload)
        self.assertNotIn("tool_choice", final_payload)
        self.assertEqual(final_payload["response_format"], {"type": "json_object"})
        self.assertEqual([m["role"] for m in final_payload["messages"]], ["system", "user"])
        self.assertNotIn("DSML", json.dumps(final_payload))
        self.assertEqual(record["request"]["reused_graph_trace_from"], source.name)
        _, cached = self.analyze(max_tokens=2048, key="")
        self.assertTrue(cached)
        self.assertEqual(len(self.calls), 3)

    def test_default_output_budget_is_omitted_and_custom_budget_is_not_clamped(self):
        record, _ = self.analyze(max_tokens=0)
        self.assertIsNone(record["request"]["max_tokens"])
        self.assertTrue(all("max_tokens" not in payload for payload, _ in self.calls))
        _, cached = self.analyze(max_tokens=None, key="")
        self.assertTrue(cached)
        self.analyze(max_tokens=32768)
        self.assertTrue(all(payload.get("max_tokens") == 32768 for payload, _ in self.calls[2:]))
        count = len(self.calls)
        for invalid in (-1, 3.5, float("inf"), float("nan"), True):
            with self.assertRaises(ValueError):
                self.analyze(max_tokens=invalid)
        self.assertEqual(len(self.calls), count)


if __name__ == "__main__":
    unittest.main()
