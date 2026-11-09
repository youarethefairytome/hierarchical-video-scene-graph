"""项目级连接环境配置；只加载指定字段，不回传保存的 Key。"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from dotenv import dotenv_values, set_key

FIELDS = ("VIDEO_LLM_BASE_URL", "VIDEO_LLM_API_KEY", "VIDEO_LLM_MODEL")
_LOCK = threading.RLock()


def load_connection_environment(root: Path):
    path = root.resolve() / ".env"
    if not path.is_file():
        return
    with _LOCK:
        values = dotenv_values(path, interpolate=False, encoding="utf-8-sig")
        for name in FIELDS:
            if isinstance(values.get(name), str):
                os.environ[name] = values[name]


def save_connection_environment(root: Path, endpoint: str, key: str, model: str):
    from video_hsg.analysis import endpoint_url

    endpoint = (endpoint or "").strip().rstrip("/")
    model = (model or "").strip()
    key = (key or "").strip()
    if not endpoint_url(endpoint):
        raise ValueError("请先填写 API 地址。")
    if any(ord(char) < 32 for char in endpoint + model):
        raise ValueError("API 地址或模型名不能包含换行等控制字符。")
    if any(ord(char) < 32 or ord(char) > 126 for char in key):
        raise ValueError("Key 中包含换行或非英文字符，请重新复制完整的 API Key。")
    root = root.resolve()
    path = root / ".env"
    with _LOCK:
        previous = dotenv_values(path, interpolate=False, encoding="utf-8-sig") if path.exists() else {}
        # 密码框留空时保留已有 Key，不要求刷新后重新输入。
        effective_key = key or previous.get("VIDEO_LLM_API_KEY") or os.getenv("VIDEO_LLM_API_KEY", "")
        values = dict(zip(FIELDS, (endpoint, effective_key, model)))
        descriptor, temporary_name = tempfile.mkstemp(prefix=".env.", dir=root)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                if path.exists():
                    handle.write(path.read_text(encoding="utf-8-sig"))
            for name, value in values.items():
                # JSON 双引号转义兼容 dotenv，interpolate=False 保留 Key 中的 $ 等字符。
                set_key(temporary, name, json.dumps(value, ensure_ascii=False), quote_mode="never")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        os.environ.update(values)
