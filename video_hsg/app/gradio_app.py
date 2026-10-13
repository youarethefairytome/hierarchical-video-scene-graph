"""层次化视频场景图 Demo。

先运行 scripts/build_scene.py 生成 processed 结果，再启动本页面。
页面只读取预处理 JSON，不重新跑 HSGG，也不把跟踪算法写进界面回调。
"""

from __future__ import annotations

import sys
from pathlib import Path

import gradio as gr
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from video_hsg.config import load_config
from video_hsg.query.search import ENTITY_COLUMNS
from video_hsg.service import ENTITY_TABLE_COLUMNS, RELATION_TABLE_COLUMNS, DemoSession

BUNDLE_PATH = ROOT / "processed" / "navqa_seq0" / "scene_bundle.json"
CYPHER_PATH = ROOT / "processed" / "navqa_seq0" / "neo4j" / "browser.cypher"
PLAIN_VIDEO = ROOT / "data" / "video" / "navqa_seq0_plain.mp4"
BOX_VIDEO = ROOT / "data" / "video" / "navqa_seq0_boxes.mp4"

VIEW_OUTPUTS = [
    "info",
    "frame",
    "frame_graph",
    "timeline",
    "clip_graph",
    "video_graph",
    "entities",
    "relations",
    "clip_text",
]


def _table(rows: list[list], columns: list[str]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns)


def _pack(view: dict):
    return (
        view["info"],
        view["frame"],
        view["frame_graph"],
        view["timeline"],
        view["clip_graph"],
        view["video_graph"],
        _table(view["entities"], ENTITY_TABLE_COLUMNS),
        _table(view["relations"], RELATION_TABLE_COLUMNS),
        view["clip_text"],
    )


def _ablation_frame(session: DemoSession) -> pd.DataFrame:
    columns = [
        ("method", "方法"),
        ("tracks", "轨迹数"),
        ("confirmed", "确认轨迹"),
        ("mean_length", "平均长度"),
        ("median_length", "中位长度"),
        ("max_length", "最长"),
        ("singleton_ratio", "碎片比例"),
        ("observations", "观测数"),
        ("accepted_matches", "接受匹配"),
        ("mean_iou", "平均IoU"),
        ("mean_attribute", "平均属性分"),
        ("mean_hierarchy", "平均层次分"),
        ("mean_relation", "平均关系分"),
        ("mean_total", "平均总分"),
    ]
    rows = []
    for item in session.bundle.get("ablation") or []:
        rows.append([item.get(key, "") for key, _ in columns])
    return pd.DataFrame(rows, columns=[title for _, title in columns])


def _video_file(show_boxes: bool):
    path = BOX_VIDEO if show_boxes else PLAIN_VIDEO
    if path.exists():
        return str(path)
    return None


def _row_dict(row_value) -> dict | None:
    if row_value is None:
        return None
    if hasattr(row_value, "to_dict"):
        return row_value.to_dict()
    if isinstance(row_value, dict):
        return row_value
    if isinstance(row_value, (list, tuple)):
        return dict(zip(ENTITY_COLUMNS, row_value))
    return None


def build_demo(session: DemoSession):
    initial = session.view(0, False, [])
    packed = _pack(initial)
    summary = session.summary
    meta = session.meta
    header = f"""
# 面向长视频理解的层次化视频场景图生成

三维视觉与视频理解 · 指导教师：阚世超

场景 `{meta["scene_id"]}`，共 **{summary["frame_count"]}** 个采样帧，
**{summary["tracks"]}** 条轨迹，**{summary["relation_count"]}** 条时间关系，
**{summary["event_count"]}** 个事件，**{summary["clip_count"]}** 个 Clip。

单帧空间层次来自已经跑好的 HSGG。原视频是 CODa 序列 0 的 cam0，按 HSGG 的每 10 帧采样对齐。勾选「播放」会按采样帧连续播放；「在原视频上显示识别框」可以随时打开或关掉框。点击查询结果会跳到对应帧。

当前已匹配原图 **{session.rgb_ready_count()}** / {summary["frame_count"]} 帧。
"""
    with gr.Blocks(title="层次化视频场景图") as demo:
        gr.Markdown(header)
        info = gr.Markdown(packed[0])
        highlight = gr.State([])
        with gr.Row():
            frame_slider = gr.Slider(
                minimum=0,
                maximum=max(session.n_frames - 1, 0),
                step=1,
                value=0,
                label="采样帧",
            )
            play = gr.Checkbox(value=False, label="播放")
            show_boxes = gr.Checkbox(value=True, label="在原视频上显示识别框")
            show_parts = gr.Checkbox(value=False, label="显示部件（窗户、把手等）")

        with gr.Tabs():
            with gr.Tab("当前帧"):
                movie = gr.Video(
                    value=_video_file(True),
                    label="整段原视频。勾选识别框后这里换成带框版本，用播放器自己的按钮连续播放。",
                    interactive=False,
                    autoplay=False,
                    loop=True,
                    height=360,
                )
                with gr.Row():
                    frame_image = gr.Image(value=packed[1], type="pil", label="当前帧（跟着上面的播放和进度条）", interactive=False)
                    frame_graph = gr.Image(value=packed[2], type="pil", label="当前帧层次场景图", interactive=False)
                with gr.Row():
                    entity_table = gr.Dataframe(
                        value=packed[6],
                        label="当前帧实体",
                        interactive=False,
                        max_height=280,
                        wrap=True,
                    )
                    relation_table = gr.Dataframe(
                        value=packed[7],
                        label="当前帧关系",
                        interactive=False,
                        max_height=280,
                        wrap=True,
                    )
            with gr.Tab("时间层次"):
                timeline = gr.Image(value=packed[3], type="pil", label="轨迹时间线", interactive=False)
                clip_text = gr.Markdown(packed[8])
                with gr.Row():
                    clip_graph = gr.Image(value=packed[4], type="pil", label="ClipGraph", interactive=False)
                    video_graph = gr.Image(value=packed[5], type="pil", label="VideoGraph", interactive=False)
            with gr.Tab("查询"):
                gr.Markdown("可查类别、轨迹号、关系或动作。例如 `building`、`person`、`near`、`holding`、`wearing`、`part_of`、`pick_up`。")
                with gr.Row():
                    query = gr.Textbox(label="查询", placeholder="building / person / near / holding", scale=3)
                    kind = gr.Radio(choices=["全部", "实体", "关系", "事件"], value="全部", label="类型", scale=2)
                    search_button = gr.Button("查询", scale=1)
                with gr.Row():
                    label_buttons = []
                    for label in session.top_labels[:8]:
                        label_buttons.append((gr.Button(label, scale=0), label))
                results = gr.Dataframe(
                    value=_table([], ENTITY_COLUMNS),
                    label="查询结果（点击一行跳到起始帧）",
                    interactive=False,
                    max_height=360,
                    wrap=True,
                    show_search="filter",
                )
            with gr.Tab("比较与 Neo4j"):
                gr.Markdown(summary.get("comparison") or "")
                gr.Dataframe(value=_ablation_frame(session), label="同一场景上的关联消融", interactive=False, wrap=True)
                gr.Markdown(
                    f"""
### 属性图

Track、Clip、Event 是节点。`SCENE_RELATION`、`PART_OF`、`SUBJECT`、`OBJECT`、`COVERS` 是关系。
页面上的 VideoGraph 用 NetworkX 画的就是这套图，所以展示不依赖 Neo4j 服务。

若本机有 Neo4j Browser，把下面文件整段粘贴执行：

`{CYPHER_PATH}`

完整节点表和关系表在同一目录的 `tracks.csv`、`relations.csv`、`events.csv`。
"""
                )

        view_outputs = [
            info,
            frame_image,
            frame_graph,
            timeline,
            clip_graph,
            video_graph,
            entity_table,
            relation_table,
            clip_text,
        ]

        def refresh(frame_id, show_parts_value, show_boxes_value, highlight_value, playing):
            if playing:
                light = session.frame_view(frame_id, bool(show_parts_value), highlight_value or [], show_boxes=bool(show_boxes_value))
                skipped = [gr.update() for _ in range(len(view_outputs) - 2)]
                return (light["info"], light["frame"], *skipped)
            return _pack(
                session.view(
                    frame_id,
                    bool(show_parts_value),
                    highlight_value or [],
                    show_boxes=bool(show_boxes_value),
                )
            )

        controls = [frame_slider, show_parts, show_boxes, highlight, play]
        frame_slider.change(refresh, controls, view_outputs)
        show_parts.change(refresh, controls, view_outputs)
        show_boxes.change(refresh, controls, view_outputs)
        show_boxes.change(lambda enabled: _video_file(bool(enabled)), show_boxes, movie)

        def tick(playing, frame_id):
            if not playing:
                return gr.update()
            nxt = int(frame_id) + 1
            if nxt >= session.n_frames:
                nxt = 0
            return nxt

        gr.Timer(0.125).tick(tick, [play, frame_slider], frame_slider)

        def do_search(text, kind_value):
            return _table(session.search(text or "", kind_value), ENTITY_COLUMNS)

        search_button.click(do_search, [query, kind], results)
        query.submit(do_search, [query, kind], results)
        for button, label in label_buttons:
            button.click(
                lambda text=label: (text, "实体", _table(session.search(text, "实体"), ENTITY_COLUMNS)),
                outputs=[query, kind, results],
            )

        def jump(show_parts_value, show_boxes_value, evt: gr.SelectData):
            data = _row_dict(evt.row_value)
            if not data or "起始采样帧" not in data:
                return gr.update(), gr.update(), *([gr.update()] * len(view_outputs))
            start = int(data["起始采样帧"])
            selected = [item for item in (data.get("主体轨迹"), data.get("客体轨迹")) if item and item != "-"]
            view = _pack(session.view(start, bool(show_parts_value), selected, show_boxes=bool(show_boxes_value)))
            return (False, start, selected, *view)

        results.select(jump, [show_parts, show_boxes], [play, frame_slider, highlight, *view_outputs])
    return demo


def main():
    if not BUNDLE_PATH.exists():
        raise SystemExit(
            "还没有预处理结果。请先在 video_hsg 目录运行:\n"
            "  python scripts/build_scene.py\n"
            "生成完成后再运行:\n"
            "  python app/gradio_app.py"
        )
    config = load_config()
    session = DemoSession.load(BUNDLE_PATH, rgb_root=config["paths"].get("rgb_root") or "")
    demo = build_demo(session)
    demo.launch(server_name="127.0.0.1", server_port=7860)


if __name__ == "__main__":
    main()
