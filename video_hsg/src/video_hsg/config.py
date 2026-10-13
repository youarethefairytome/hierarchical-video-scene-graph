"""读取 YAML，并把相对路径解析到项目根目录。"""

from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def resolve_path(root: Path, value: str | None) -> str:
    if not value:
        return ""
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    return str(path.resolve())


def load_config(path: Path | None = None) -> dict:
    config_path = path or (PROJECT_ROOT / "configs" / "default.yaml")
    with config_path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"配置文件不是映射: {config_path}")
    paths = config.setdefault("paths", {})
    for key in ("scene_dir", "output_dir", "rgb_root"):
        paths[key] = resolve_path(PROJECT_ROOT, paths.get(key) or "")
    return config
