"""模型列表的真实 HTTP 读取、鉴权、地址兼容及错误处理。"""
import json
import sys
import threading
import unittest
import urllib.error
import ssl
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from video_hsg.analysis import API_USER_AGENT, ModelCatalogError, list_models


class ModelCatalogTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.user_agents = []
        self.status = 200
        self.response = {"data": [{"id": "model-b"}, {"id": " model-a "}, {"id": "model-b"}, {"id": ""}, {}]}
        case = self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                case.calls.append((self.path, self.headers.get("Authorization")))
                case.user_agents.append(self.headers.get("User-Agent"))
                self.send_response(case.status)
                self.send_header("Content-Type", "application/json")
                if case.status == 302:
                    self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/redirect-target")
                self.end_headers()
                self.wfile.write(json.dumps(case.response).encode())
            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}/gateway/v1"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_base_and_completion_addresses_use_get_models(self):
        for suffix in ("", "/", "/chat/completions", "/models"):
            self.assertEqual(list_models(self.base + suffix, " test-key "), ["model-a", "model-b"])
        self.assertEqual(self.calls, [("/gateway/v1/models", "Bearer test-key")] * 4)
        self.assertEqual(self.user_agents, [API_USER_AGENT] * 4)

    def test_empty_catalog_public_server_and_bad_payload(self):
        self.response = {"data": []}
        self.assertEqual(list_models(self.base), [])
        self.assertIsNone(self.calls[-1][1])
        for response in ({"error": "invalid"}, {"data": [{}]}, {"data": "wrong"}):
            self.response = response
            with self.assertRaises(ValueError):
                list_models(self.base)

    def test_errors_and_redirect_do_not_retry_or_forward_key(self):
        for status, text in ((401, "HTTP 401"), (404, "HTTP 404"), (500, "HTTP 500"), (302, "HTTP 302")):
            self.status = status
            count = len(self.calls)
            with self.assertRaisesRegex(ValueError, text):
                list_models(self.base, "test-key")
            self.assertEqual(len(self.calls), count + 1)
        for address in ("", "https://user:secret@example.com/v1", self.base + "?key=secret"):
            count = len(self.calls)
            with self.assertRaises(ValueError):
                list_models(address)
            self.assertEqual(len(self.calls), count)

    def test_provider_errors_distinguish_gateway_denial_and_hide_key(self):
        self.status = 403
        self.response = {"cloudflare_error": True, "error_code": 1010, "detail": "browser signature denied"}
        with self.assertRaises(ModelCatalogError) as captured:
            list_models(self.base, "test-key")
        self.assertIn("网关", str(captured.exception))
        self.assertIn("1010", captured.exception.detail)
        self.response = {"error": {"code": "token_expired", "message": "expired credential test-key"}}
        with self.assertRaises(ModelCatalogError) as captured:
            list_models(self.base, "test-key")
        self.assertNotIn("test-key", captured.exception.detail)
        self.assertIn("token_expired", captured.exception.detail)
        self.assertEqual(captured.exception.url, self.base + "/models")

    def test_response_variants_and_key_validation(self):
        for response in (["model-a", {"id": "model-b"}], {"models": [{"name": "model-a"}, {"name": "model-b"}]},
                         {"data": {"models": ["model-a", "model-b"]}}):
            self.response = response
            self.assertEqual(list_models(self.base), ["model-a", "model-b"])
        for key in ("first\nsecond", "中文-key"):
            count = len(self.calls)
            with self.assertRaisesRegex(ValueError, "Key"):
                list_models(self.base, key)
            self.assertEqual(len(self.calls), count)

    def test_certificate_and_timeout_errors_have_specific_actions(self):
        for reason, message in ((TimeoutError(), "超时"), (ssl.SSLCertVerificationError(), "证书")):
            with patch("urllib.request.OpenerDirector.open", side_effect=urllib.error.URLError(reason)):
                with self.assertRaisesRegex(ModelCatalogError, message) as captured:
                    list_models(self.base)
                self.assertTrue(captured.exception.suggestion)


if __name__ == "__main__":
    unittest.main()
