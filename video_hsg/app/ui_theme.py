"""演示界面的主题和轻量展示元素，不依赖外部字体或图标服务。"""
from __future__ import annotations

from html import escape
from pathlib import Path

import gradio as gr

APP_CSS = (Path(__file__).with_name("ui.css")).read_text(encoding="utf-8")


def build_theme():
    theme = gr.themes.Soft(
        primary_hue="teal", secondary_hue="teal", neutral_hue="slate",
        font=["Segoe UI", "Microsoft YaHei", "PingFang SC", "sans-serif"],
    )
    colors = {
        "body_background_fill": "#f3f6f8", "body_text_color": "#213247",
        "body_text_color_subdued": "#738195", "background_fill_primary": "#ffffff",
        "background_fill_secondary": "#f6f8fa", "block_background_fill": "#ffffff",
        "block_border_color": "#e4eaf0", "block_label_background_fill": "transparent",
        "block_label_text_color": "#66768b", "block_title_text_color": "#34475d",
        "border_color_primary": "#e1e8ee", "border_color_accent": "#1c8076",
        "input_background_fill": "#f8fafb", "input_border_color": "#dfe7ed",
        "input_placeholder_color": "#8b98a8", "input_shadow": "none",
        "button_primary_background_fill": "#16756b", "button_primary_background_fill_hover": "#115f57",
        "button_primary_border_color": "#16756b", "button_primary_border_color_hover": "#115f57",
        "button_primary_text_color": "#ffffff", "button_primary_text_color_hover": "#ffffff",
        "button_secondary_background_fill": "#ffffff", "button_secondary_background_fill_hover": "#edf5f3",
        "button_secondary_border_color": "#dce5e9", "button_secondary_border_color_hover": "#a3c7c1",
        "button_secondary_text_color": "#42566b", "button_secondary_text_color_hover": "#12675e",
    }
    # 统一明暗系统偏好下的展示效果，避免默认深色控件混入浅色卡片。
    available = theme.to_dict()["theme"]
    values = {}
    for name, value in colors.items():
        if name in available:
            values[name] = value
        if name + "_dark" in available:
            values[name + "_dark"] = value
    return theme.set(**values, block_shadow="none", block_radius="12px",
                     button_large_radius="10px", button_medium_radius="10px", button_small_radius="8px")


def icon(name: str) -> str:
    paths = {
        "graph": '<path d="M7 6h10M6 8v8m12-8v8M8 18h8M8 8l8 8"/><circle cx="5" cy="5" r="3"/><circle cx="19" cy="5" r="3"/><circle cx="5" cy="19" r="3"/><circle cx="19" cy="19" r="3"/>',
        "video": '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="m10 9 5 3-5 3z"/>',
        "insight": '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z"/>',
        "entity": '<rect x="4" y="4" width="6" height="6" rx="1.5"/><rect x="14" y="4" width="6" height="6" rx="1.5"/><rect x="4" y="14" width="6" height="6" rx="1.5"/><rect x="14" y="14" width="6" height="6" rx="1.5"/>',
        "event": '<path d="M4 7h16M8 3v4m8-4v4"/><rect x="4" y="5" width="16" height="16" rx="3"/><path d="m9 14 2 2 4-4"/>',
        "history": '<path d="M3 11a9 9 0 1 1 3 8M3 4v7h7m2-4v5l3 2"/>',
    }
    return f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{paths[name]}</svg>'


def app_header() -> str:
    return f'''<header class="app-masthead">
      <div class="brand-lockup"><div class="brand-mark">{icon("graph")}</div><div>
        <div class="brand-caption">VIDEO SCENE GRAPH</div><h1>层次化视频场景图</h1>
        <p>三维视觉与视频理解 <span>·</span> 指导教师：阚世超</p>
      </div></div><div class="workspace-badge"><i></i> 演示工作台</div>
    </header>'''


def panel_heading(kind: str, title: str, caption: str) -> str:
    return f'<div class="panel-heading"><span class="panel-icon">{icon(kind)}</span><div><h3>{escape(title)}</h3><p>{escape(caption)}</p></div></div>'


def video_details(video: dict | None) -> str:
    if not video:
        return '<div class="video-facts"><span class="fact-chip">等待导入视频</span></div>'
    camera = {"fixed": "固定镜头", "moving": "移动镜头"}.get(video["camera"], "本地视频")
    duration = f"{int(video['duration']) // 60:02d}:{int(video['duration']) % 60:02d}"
    source = str(video["source"])
    source_label = "NExT-QA 数据集" if video.get("dataset") == "NExT-QA" else "CODa 数据集" if "utexas.edu" in source else "本地导入"
    if source.startswith(("https://", "http://")):
        source_label = f'<a href="{escape(source, quote=True)}" target="_blank" rel="noopener noreferrer">{escape(source_label)} ↗</a>'
    return f'''<div class="video-facts"><span class="fact-chip camera-chip"><i></i>{camera}</span>
      <span class="fact-chip">{duration}</span><span class="fact-chip">{video['width']} × {video['height']}</span>
      <span class="video-source">{source_label}</span></div>
      <p class="video-description">{escape(video.get('description', ''))}</p>'''


def result_metrics(record: dict | None, history_count: int) -> str:
    result = record["result"] if record else {}
    values = [("entity", len(result["entities"]) if record else "—", "重要实体"),
              ("event", len(result["events"]) if record else "—", "关键事件"),
              ("history", history_count, "历史记录")]
    return '<div class="result-metrics">' + "".join(
        f'<div class="metric"><span class="metric-icon {name}">{icon(name)}</span><div><strong>{value}</strong><span>{label}</span></div></div>'
        for name, value, label in values) + '</div>'


EMPTY_RESULT = f'''<div class="result-empty"><div class="empty-illustration">{icon("insight")}</div>
    <h4>从场景图理解视频</h4><p>搜索已有节点、关系和事件，生成可核对的概括。<br>已有结果？从历史记录中选择，或在下方导入。</p>
    <div class="empty-steps"><span>01 选择视频场景</span><b>→</b><span>02 图检索理解</span><b>→</b><span>03 保存回放</span></div></div>'''
