"""层次化视频场景图 Demo。

所有标签页使用顶部统一选择的视频；没有对应场景图时显示待处理。
页面只读取绑定的预处理 JSON，不重新跑 HSGG，也不把跟踪算法写进界面回调。
"""

from __future__ import annotations

import sys
from pathlib import Path

import gradio as gr
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
LAYERED_JS = (ROOT / "app" / "layered_view.js").read_text(encoding="utf-8")
TIMELINE_JS = (ROOT / "app" / "timeline_view.js").read_text(encoding="utf-8")
TIMELINE_HTML = """
<div class="stage">
  <canvas></canvas>
  <button class="reset" type="button">复位视角</button>
  <label class="hide-text"><input class="hide-labels" type="checkbox"> 不显示文字</label>
  <div class="hud">拖动旋转，滚轮缩放，点击节点。底部进度条移动 X 轴并放大到该帧。</div>
  <div class="scrub">
    <span>X</span>
    <input class="x-slider" type="range" min="0" max="1" value="0" step="1">
    <span class="x-readout">全段</span>
  </div>
</div>
"""
TIMELINE_CSS = """
.stage { position: relative; height: 720px; background: #f7f8fb; border-radius: 12px; overflow: hidden; }
canvas { width: 100%; height: calc(100% - 56px); display: block; touch-action: none; cursor: grab; }
.reset { position: absolute; top: 10px; right: 10px; border: 0; border-radius: 8px; padding: 6px 10px; background: #1f4e79; color: white; cursor: pointer; }
.hide-text { position: absolute; top: 10px; left: 12px; background: rgba(255,255,255,0.92); border-radius: 8px; padding: 6px 10px; font-size: 13px; color: #1f2937; cursor: pointer; }
.hud { position: absolute; left: 12px; bottom: 64px; max-width: 52%; background: rgba(255,255,255,0.92); border-radius: 10px; padding: 8px 10px; font-size: 13px; line-height: 1.45; color: #1f2937; }
.scrub { position: absolute; left: 12px; right: 12px; bottom: 10px; display: flex; align-items: center; gap: 10px; background: rgba(255,255,255,0.94); border-radius: 10px; padding: 8px 12px; }
.x-slider { flex: 1; }
.x-readout { min-width: 96px; font-size: 13px; color: #1f2937; }
"""
LAYERED_HTML = """
<div class="stage">
  <canvas></canvas>
  <button class="reset" type="button">复位视角</button>
  <label class="hide-text"><input class="hide-labels" type="checkbox"> 不显示文字</label>
  <div class="hud">拖动旋转，滚轮缩放，点击节点</div>
</div>
"""
LAYERED_CSS = """
.stage { position: relative; height: 640px; background: #fbfbfd; border-radius: 12px; overflow: hidden; }
canvas { width: 100%; height: 100%; display: block; touch-action: none; cursor: grab; }
.reset { position: absolute; top: 10px; right: 10px; border: 0; border-radius: 8px; padding: 6px 10px; background: #1f4e79; color: white; cursor: pointer; }
.hide-text { position: absolute; top: 10px; left: 12px; background: rgba(255,255,255,0.92); border-radius: 8px; padding: 6px 10px; font-size: 13px; color: #1f2937; cursor: pointer; }
.hud { position: absolute; left: 12px; bottom: 12px; max-width: 46%; background: rgba(255,255,255,0.92); border-radius: 10px; padding: 8px 10px; font-size: 13px; line-height: 1.45; color: #1f2937; }
"""

from video_hsg.query.search import ENTITY_COLUMNS
from video_hsg.service import ENTITY_TABLE_COLUMNS, RELATION_TABLE_COLUMNS, DemoSession
from video_hsg.analysis import AnalysisWorkspace
from video_hsg.video_workspace import VideoSceneRegistry
from analysis_tab import build_analysis_tab
from ui_theme import APP_CSS, app_header, build_theme

def _table(rows: list[list], columns: list[str]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns)


def _pack(view: dict):
    return (
        view["info"],
        view["frame"],
        view["layered"],
        view["timeline"],
        view["clip_graph"],
        view["video_graph"],
        _table(view["entities"], ENTITY_TABLE_COLUMNS),
        _table(view["relations"], RELATION_TABLE_COLUMNS),
        view["clip_text"],
    )


def _ablation_frame(session: DemoSession | None) -> pd.DataFrame:
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
    items = (session.bundle.get("ablation") or []) if session else []
    for item in items:
        rows.append([item.get(key, "") for key, _ in columns])
    return pd.DataFrame(rows, columns=[title for _, title in columns])



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


def build_demo(workspace: AnalysisWorkspace | None = None):
    workspace = workspace or AnalysisWorkspace(ROOT)
    registry = VideoSceneRegistry(workspace)
    videos = workspace.videos()
    if not videos:
        raise ValueError("没有可用视频，请先运行 python scripts/prepare_nextqa_demo.py。")
    initial_id = videos[0]["id"]
    initial_scene = registry.get(initial_id)
    packed = _pack(initial_scene.view(0, show_boxes=initial_scene.has_graph))
    queue_id = "video-workspace"

    with gr.Blocks(title="层次化视频场景图", analytics_enabled=False) as demo:
        gr.HTML(app_header())
        with gr.Group(elem_id="global-video-selector"):
            video_picker = gr.Dropdown(
                choices=[(video["title"], video["id"]) for video in videos], value=initial_id,
                label="当前展示视频（所有页面同步）", elem_id="active-video")
            scene_notice = gr.Markdown(initial_scene.notice)
        highlight = gr.State([])
        search_origin = gr.State("")

        with gr.Tabs(elem_id="workspace-tabs", overflow_behavior="wrap"):
            with gr.Tab("视频理解与演示", elem_id="video-workspace"):
                analysis_panel = build_analysis_tab(workspace, video_picker, concurrency_id=queue_id)
            with gr.Tab("当前帧"):
                info = gr.Markdown(packed[0])
                with gr.Row():
                    frame_slider = gr.Slider(minimum=0, maximum=max(initial_scene.n_frames - 1, 1),
                                             step=1, value=0, label="采样 / 预览帧")
                    play = gr.Checkbox(value=False, label="播放")
                    show_boxes = gr.Checkbox(value=initial_scene.has_graph, interactive=initial_scene.has_graph,
                                             label="显示当前视频的识别框")
                    show_parts = gr.Checkbox(value=False, interactive=initial_scene.has_graph, label="显示部件")
                movie = gr.Video(value=initial_scene.video_file(initial_scene.has_graph), label="当前选择的视频",
                                 interactive=False, autoplay=False, loop=True, height=360)
                with gr.Row():
                    frame_image = gr.Image(value=packed[1], type="pil", label="当前视频画面", interactive=False)
                    frame_graph = gr.HTML(value=packed[2], html_template=LAYERED_HTML,
                                          css_template=LAYERED_CSS, js_on_load=LAYERED_JS,
                                          min_height=640, label="当前视频的五层场景图")
                with gr.Row():
                    entity_table = gr.Dataframe(value=packed[6], label="当前帧实体", interactive=False,
                                                max_height=280, wrap=True)
                    relation_table = gr.Dataframe(value=packed[7], label="当前帧关系", interactive=False,
                                                  max_height=280, wrap=True)
            with gr.Tab("全视频三层"):
                gr.Markdown("展示顶部所选视频的三层图。X 为时间，Z 从上到下为 L1、L2、L3；Y 为画面里的左右位置。读取当前视频已绑定的 HSGG 结果。")
                whole_timeline = gr.HTML(value=initial_scene.timeline_json(), html_template=TIMELINE_HTML,
                                         css_template=TIMELINE_CSS, js_on_load=TIMELINE_JS, min_height=720)
            with gr.Tab("时间层次"):
                timeline = gr.Image(value=packed[3], type="pil", label="当前视频的轨迹时间线", interactive=False)
                clip_text = gr.Markdown(packed[8])
                with gr.Row():
                    clip_graph = gr.Image(value=packed[4], type="pil", label="ClipGraph", interactive=False)
                    video_graph = gr.Image(value=packed[5], type="pil", label="VideoGraph", interactive=False)
            with gr.Tab("查询"):
                gr.Markdown("查询范围为顶部选择的视频，可查实体、轨迹、关系或事件。查询数据来自已绑定的 HSGG 预处理结果。")
                with gr.Row():
                    query = gr.Textbox(label="查询", placeholder="输入类别、轨迹号、关系或动作", scale=3)
                    kind = gr.Radio(choices=["全部", "实体", "关系", "事件"], value="全部", label="类型", scale=2)
                    search_button = gr.Button("查询", scale=1)
                with gr.Row():
                    label_buttons = []
                    labels = initial_scene.top_labels[:8]
                    for index in range(8):
                        label_buttons.append(gr.Button(labels[index] if index < len(labels) else "",
                                                       visible=index < len(labels), scale=0))
                results = gr.Dataframe(value=_table([], ENTITY_COLUMNS), label="查询结果（点击一行跳到起始帧）",
                                       interactive=False, max_height=360, wrap=True, show_search="filter")
            with gr.Tab("比较与 Neo4j"):
                comparison = gr.Markdown(initial_scene.comparison)
                ablation = gr.Dataframe(value=_ablation_frame(initial_scene.session), label="当前视频的关联消融",
                                        interactive=False, wrap=True)
                neo4j = gr.Markdown(initial_scene.neo4j_text)

        view_outputs = [info, frame_image, frame_graph, timeline, clip_graph, video_graph,
                        entity_table, relation_table, clip_text]
        scene_outputs = [scene_notice, frame_slider, play, show_boxes, show_parts, highlight, movie,
                         whole_timeline, comparison, ablation, neo4j, query, kind, results, search_origin,
                         *label_buttons, *view_outputs]
        all_outputs = [*analysis_panel.selection_outputs, *scene_outputs]

        def select_scene(video_id):
            scene = registry.get(video_id)
            labels = scene.top_labels[:8]
            buttons = [gr.update(value=labels[index] if index < len(labels) else "", visible=index < len(labels))
                       for index in range(len(label_buttons))]
            return (*analysis_panel.select_video(video_id), scene.notice,
                    gr.update(maximum=max(scene.n_frames - 1, 1), value=0), False,
                    gr.update(value=scene.has_graph, interactive=scene.has_graph),
                    gr.update(value=False, interactive=scene.has_graph), [], scene.video_file(scene.has_graph),
                    scene.timeline_json(), scene.comparison, _ablation_frame(scene.session), scene.neo4j_text,
                    "", "全部", _table([], ENTITY_COLUMNS), "", *buttons,
                    *_pack(scene.view(0, show_boxes=scene.has_graph)))

        # 同一次响应更新全部页面；每个浏览器会话独立选择，不修改共享的 current_session。
        video_picker.change(select_scene, video_picker, all_outputs,
                            concurrency_limit=1, concurrency_id=queue_id, trigger_mode="always_last")
        demo.load(select_scene, video_picker, all_outputs, concurrency_id=queue_id, api_name="initialize_video")

        def refresh(video_id, frame_id, show_parts_value, show_boxes_value, highlight_value, playing):
            scene = registry.get(video_id)
            if playing and scene.has_graph:
                light = scene.frame_view(frame_id, bool(show_parts_value), highlight_value or [], show_boxes=bool(show_boxes_value))
                return (light["info"], light["frame"], scene.layered_json(int(frame_id)),
                        *[gr.update() for _ in range(len(view_outputs) - 3)])
            return _pack(scene.view(frame_id, bool(show_parts_value), highlight_value or [], show_boxes=bool(show_boxes_value)))

        controls = [video_picker, frame_slider, show_parts, show_boxes, highlight, play]
        frame_slider.change(refresh, controls, view_outputs, concurrency_id=queue_id)
        show_parts.input(refresh, controls, view_outputs, concurrency_id=queue_id)
        show_boxes.input(refresh, controls, view_outputs, concurrency_id=queue_id)

        def video_file(video_id, boxes):
            return registry.get(video_id).video_file(bool(boxes))

        show_boxes.input(video_file, [video_picker, show_boxes], movie, concurrency_id=queue_id)

        def tick(video_id, playing, frame_id):
            if not playing:
                return gr.update()
            return (int(frame_id) + 1) % registry.get(video_id).n_frames

        timer = gr.Timer(0.125, active=False)
        timer.tick(tick, [video_picker, play, frame_slider], frame_slider, concurrency_id=queue_id)
        play.change(lambda enabled: gr.update(active=bool(enabled)), play, timer, queue=False)

        def do_search(video_id, text, kind_value):
            return _table(registry.get(video_id).search(text or "", kind_value), ENTITY_COLUMNS), video_id

        search_button.click(do_search, [video_picker, query, kind], [results, search_origin], concurrency_id=queue_id)
        query.submit(do_search, [video_picker, query, kind], [results, search_origin], concurrency_id=queue_id)

        def quick_search(video_id, label):
            return label, "实体", _table(registry.get(video_id).search(label, "实体"), ENTITY_COLUMNS), video_id

        for button in label_buttons:
            button.click(quick_search, [video_picker, button], [query, kind, results, search_origin], concurrency_id=queue_id)

        def jump(video_id, origin_video, show_parts_value, show_boxes_value, evt: gr.SelectData):
            scene = registry.get(video_id)
            data = _row_dict(evt.row_value)
            if origin_video != video_id or not scene.has_graph or not data or "起始采样帧" not in data:
                return tuple(gr.update() for _ in range(3 + len(view_outputs)))
            start = int(data["起始采样帧"])
            selected = [item for item in (data.get("主体轨迹"), data.get("客体轨迹")) if item and item != "-"]
            return False, start, selected, *_pack(scene.view(start, bool(show_parts_value), selected,
                                                           show_boxes=bool(show_boxes_value)))

        results.select(jump, [video_picker, search_origin, show_parts, show_boxes],
                       [play, frame_slider, highlight, *view_outputs], concurrency_id=queue_id)
    return demo


def main():
    demo = build_demo()
    demo.launch(server_name="127.0.0.1", server_port=7860, theme=build_theme(), css=APP_CSS, footer_links=[],
                blocked_paths=[str(ROOT / ".env")])


if __name__ == "__main__":
    main()
