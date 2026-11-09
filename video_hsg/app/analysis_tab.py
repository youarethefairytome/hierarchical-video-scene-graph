"""视频理解页：视频切换、API 分析、历史回放与 JSON 导入导出。"""
from __future__ import annotations

import os
from html import escape
from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

import cv2
import gradio as gr
import pandas as pd

from video_hsg.analysis import AnalysisWorkspace, DEFAULT_PROMPT, ModelCatalogError, list_models
from video_hsg.connection_settings import save_connection_environment
from ui_theme import EMPTY_RESULT, panel_heading, result_metrics, video_details

ENTITY_COLUMNS = ["实体 ID", "名称", "类别", "图中属性与重要性", "证据时间（秒）", "图节点引用"]
EVENT_COLUMNS = ["开始（秒）", "结束（秒）", "涉及实体", "事件描述", "图证据引用"]


def configured_endpoint():
    return os.getenv("VIDEO_LLM_BASE_URL", "")


def configured_model():
    return os.getenv("VIDEO_LLM_MODEL", "").strip() or None


def connection_feedback():
    has_key = bool(os.getenv("VIDEO_LLM_API_KEY", "").strip())
    return _model_feedback("info", "已配置 Key，输入框留空即可使用。" if has_key else "尚未保存 Key，请填写后保存连接设置。",
                           "保存后更新服务环境变量，并写入本机项目 .env；刷新和重启后可继续使用。")


def _model_feedback(level, title, detail="", suggestion="", url=""):
    role = "alert" if level == "error" else "status"
    parts = [f'<div class="model-feedback {level}" role="{role}" aria-live="polite"><strong>{escape(title)}</strong>']
    for text in (detail, suggestion):
        if text:
            parts.append(f'<p>{escape(text)}</p>')
    if url:
        parts.append(f'<p class="model-request-url">请求地址：<code>{escape(url)}</code></p>')
    return "".join(parts) + "</div>"


@dataclass
class AnalysisPanel:
    selection_outputs: list
    select_video: Callable


def build_analysis_tab(workspace: AnalysisWorkspace, video_picker=None, *, concurrency_id="analysis"):
    standalone = video_picker is None
    def video_choices():
        return [(v["title"], v["id"]) for v in workspace.videos()]

    def history_choices(video_id):
        choices = []
        for record in workspace.history(video_id):
            time = datetime.fromisoformat(record["created_at"]).astimezone(ZoneInfo("Asia/Shanghai")).strftime("%m-%d %H:%M:%S")
            origin = ("图检索分析" if record["request"].get("input_mode") == "scene_graph_tools" else "旧版画面分析") if record["origin"] == "api" else "导入结果"
            model = record["request"].get("model", "")
            choices.append((f"{time} · {origin} · {model} · {record['id'][:6]}", record["id"]))
        return choices

    def presentation(record=None):
        if not record:
            return ("", pd.DataFrame(columns=ENTITY_COLUMNS), pd.DataFrame(columns=EVENT_COLUMNS),
                    "", {}, None, "", None, result_metrics(None, 0), gr.update(visible=True), [])
        result = record["result"]
        entities = [[e["id"], e["name"], e["category"], e["description"],
                     ", ".join(str(t) for t in e["evidence_seconds"]), ", ".join(e.get("graph_node_ids", []))] for e in result["entities"]]
        events = [[e["start_seconds"], e["end_seconds"], ", ".join(e["entity_ids"]), e["description"], ", ".join(e.get("graph_evidence", []))] for e in result["events"]]
        origin = ("场景图检索分析" if record["request"].get("input_mode") == "scene_graph_tools" else "旧版画面分析，仅供历史回放") if record["origin"] == "api" else "外部导入（未验证模型来源）"
        evidence = record.get("evidence") or []
        saved_time = datetime.fromisoformat(record["created_at"]).astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
        meta = f"来源：{origin} | 保存时间：{saved_time}（北京时间） | 模型：{record['request'].get('model', '未记录')} | 图检索记录：{len(evidence) if record["request"].get("input_mode") == "scene_graph_tools" else 0} 条"
        if record.get("usage"):
            meta += f" | 用量：{record['usage']}"
        if record["request"].get("reused_graph_trace_from"):
            meta += " | 已复用上次图检索，仅生成最终概括"
        return (result["summary"], pd.DataFrame(entities, columns=ENTITY_COLUMNS),
                pd.DataFrame(events, columns=EVENT_COLUMNS), result.get("limitations", ""), record,
                workspace.export(record["id"]), meta, record["id"],
                result_metrics(record, len(workspace.history(record["video"]["id"]))), gr.update(visible=False), evidence if record["request"].get("input_mode") == "scene_graph_tools" else [])

    def describe(video):
        return video_details(video)

    choices = video_choices()
    initial_id = (choices[0][1] if choices else None) if standalone else video_picker.value
    initial_video = workspace.video(initial_id) if initial_id else None
    histories = history_choices(initial_id) if initial_id else []
    initial_record = workspace.run(histories[0][1]) if histories else None
    display = presentation(initial_record)

    gr.HTML('<div class="analysis-intro"><h2>视频理解与演示</h2><p>从已有场景图检索节点与关系，理解重要实体、事件和视频内容。</p></div>')
    with gr.Row(elem_classes="analysis-layout"):
        with gr.Column(scale=6, min_width=330, elem_classes=["surface-card", "media-panel"]):
            gr.HTML(panel_heading("video", "视频素材", "画面用于人工对照，模型读取已有场景图"))
            if standalone:
                video_picker = gr.Dropdown(choices=choices, value=initial_id, label="展示视频", elem_classes="compact-picker")
            video_description = gr.HTML(describe(initial_video))
            movie = gr.Video(value=initial_video["path"] if initial_video else None, label="视频预览", interactive=False,
                             height=390, elem_id="analysis-video", show_label=False, container=False)
            with gr.Accordion("事件证据 · 定位到对应画面", open=False, elem_classes="quiet-accordion") as evidence_panel:
                evidence_time = gr.Slider(minimum=0, maximum=initial_video["duration"] if initial_video else 1,
                                          value=0, step=0.1, label="证据时间（秒）")
                evidence_image = gr.Image(label="对应视频画面", interactive=False, height=240)
            gr.Markdown("点击右侧事件，可自动定位视频并展开证据画面。", elem_classes="helper-text")
        with gr.Column(scale=5, min_width=340, elem_classes=["surface-card", "insights-panel"]):
            gr.HTML(panel_heading("insight", "理解结果", "每一次分析，都可以保存与回放"))
            with gr.Row(elem_classes="history-row"):
                history = gr.Dropdown(choices=histories, value=initial_record["id"] if initial_record else None,
                                      label="历史记录", scale=5, elem_classes="compact-picker",
                                      allow_custom_value=False)
                refresh_history = gr.Button("刷新", scale=0, min_width=58, elem_classes="history-refresh")
            overview = gr.HTML(display[8])
            with gr.Tabs(elem_id="analysis-result-tabs"):
                with gr.Tab("视频概括"):
                    empty = gr.HTML(EMPTY_RESULT, visible=not bool(initial_record))
                    summary = gr.Markdown(value=display[0], line_breaks=True, elem_classes="insight-prose")
                    with gr.Accordion("证据范围与不确定性", open=False, elem_classes="quiet-accordion"):
                        limitations = gr.Markdown(value=display[3], elem_classes="helper-text")
                with gr.Tab("重要实体"):
                    entities = gr.Dataframe(value=display[1], interactive=False, wrap=True, label="重要实体",
                                            show_label=False, max_height=400, elem_classes="result-table")
                with gr.Tab("实体事件"):
                    events = gr.Dataframe(value=display[2], interactive=False, wrap=True, label="事件列表（点击一行查看证据）",
                                          show_label=False, max_height=400, elem_classes="result-table")
                with gr.Tab("图检索过程"):
                    graph_trace = gr.JSON(value=display[10], label="模型查询与返回的图证据")
                with gr.Tab("记录与导出"):
                    metadata = gr.Textbox(value=display[6], label="结果记录", interactive=False, lines=3)
                    restore_settings = gr.Button("恢复这次分析的调用参数", size="sm")
                    download = gr.File(value=display[5], label="下载结果 JSON", interactive=False)
                    with gr.Accordion("查看结构化原始记录", open=False, elem_classes="quiet-accordion"):
                        archive = gr.JSON(value=display[4], label="结构化结果及调用参数")
            status = gr.Markdown("已加载历史结果，可以直接展示。" if initial_record else "准备就绪。请配置支持工具调用的文本模型，分析将查询当前视频的已有场景图。",
                                 elem_classes="analysis-status")
            with gr.Row(elem_classes="analysis-actions"):
                analyze_button = gr.Button("开始分析 / 读取缓存", variant="primary", scale=3, min_width=160)
                force_button = gr.Button("重新分析 · 调用 API", scale=2, min_width=140, elem_classes="analysis-secondary")

    with gr.Accordion("模型与分析设置", open=False, elem_classes="analysis-settings"):
        gr.Markdown("使用支持工具调用（Function Calling）的文本模型。模型查询已有节点、关系、事件及帧级图，不上传视频或图片。每轮最多执行 2 次图查询，最多调用 API 的次数为检索轮数 + 1。点击保存可将连接信息写入项目环境配置，Key 不写入分析记录。", elem_classes="helper-text")
        with gr.Row():
            endpoint = gr.Textbox(value=configured_endpoint, label="API 地址",
                                  placeholder="https://你的服务地址/v1")
            default_model = os.getenv("VIDEO_LLM_MODEL", "").strip()
            model = gr.Dropdown(choices=[default_model] if default_model else [], value=configured_model,
                                label="文本模型（支持工具调用）", allow_custom_value=True,
                                filterable=True, interactive=True)
            key = gr.Textbox(label="API Key", type="password", placeholder="留空保留并使用已保存的 Key；填写新值可更新")
        with gr.Row():
            fetch_models_button = gr.Button("获取可用模型", size="sm", scale=0, min_width=130)
            model_list_status = gr.HTML(_model_feedback("info", "填写 API 地址和 Key 后获取列表，也可直接输入模型名。"))
        with gr.Row():
            save_connection_button = gr.Button("保存连接设置", size="sm", scale=0, min_width=130)
            connection_status = gr.HTML(value=connection_feedback)
        prompt = gr.Textbox(value=DEFAULT_PROMPT, label="分析要求", lines=3)
        with gr.Row():
            search_rounds = gr.Slider(minimum=1, maximum=6, step=1, value=3, label="最多图检索轮数")
            max_tokens = gr.Number(value=0, minimum=0, precision=0, label="输出 token 上限（0 = 服务商默认）",
                                   info="默认不发送 max_tokens，应用不额外限制输出。可填写正整数自定义；服务商和模型本身仍有长度限制。")
    with gr.Row(elem_classes="utility-row"):
        with gr.Column(min_width=280):
            with gr.Accordion("添加视频素材", open=False, elem_classes="analysis-settings"):
                gr.Markdown("导入视频用于人工预览；进行 AI 图理解前，需在视频目录配置中绑定对应已有 HSGG 结果。", elem_classes="helper-text")
                video_file = gr.File(label="本地视频", file_types=[".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"], type="filepath")
                video_title = gr.Textbox(label="展示名称（可选）", placeholder="例如：固定机位 · 教室活动")
                add_video = gr.Button("加入视频库", size="sm")
        with gr.Column(min_width=280):
            with gr.Accordion("导入已有分析结果", open=False, elem_classes="analysis-settings"):
                gr.Markdown("导入之前保存的结果 JSON，即可直接回放展示。", elem_classes="helper-text")
                result_file = gr.File(label="结果 JSON", file_types=[".json"], type="filepath")
                import_button = gr.Button("保存并展示结果", size="sm")
    gr.Markdown("分析结果自动保存 · 相同参数优先读取缓存 · 所有标签页跟随顶部视频选择", elem_classes="workspace-footnote")
    selected_run = gr.State(display[7])
    result_outputs = [summary, entities, events, limitations, archive, download, metadata, selected_run, overview, empty, graph_trace]

    def select_video(video_id):
        video = workspace.video(video_id)
        choices = history_choices(video_id)
        record = workspace.run(choices[0][1]) if choices else None
        message = "**已回放本地历史，未调用 API。**" if record else "**该视频暂无历史结果。** 可配置文本模型查询已有场景图，或导入已有结果。"
        return (video["path"], describe(video), gr.update(choices=choices, value=record["id"] if record else None),
                message, gr.update(maximum=video["duration"], value=0), None, *presentation(record))

    selection_outputs = [movie, video_description, history, status, evidence_time, evidence_image, *result_outputs]
    if standalone:
        video_picker.change(select_video, video_picker, selection_outputs, concurrency_id=concurrency_id)

    def upload(path, title):
        if not path:
            raise gr.Error("请先选择本地视频文件。")
        try:
            item = workspace.upload(path, title or "")
            return gr.update(choices=video_choices(), value=item["id"])
        except ValueError as error:
            raise gr.Error(str(error)) from None

    add_video.click(upload, [video_file, video_title], video_picker, concurrency_limit=1, concurrency_id=concurrency_id)

    def load_history(run_id, video_id):
        if not run_id:
            return (*presentation(), "**该视频暂无历史结果。**")
        record = workspace.run(run_id)
        video = workspace.video(video_id)
        if record["video"]["id"] != video_id or record["video"]["sha256"] != video["sha256"]:
            raise gr.Error("历史与所选视频不匹配，请刷新历史。")
        return (*presentation(record), "**已回放本地历史，未调用 API。**")

    # input 仅响应用户操作；程序写入下拉框时不覆盖“缓存命中”等状态。
    history.input(load_history, [history, video_picker], [*result_outputs, status], concurrency_id=concurrency_id)
    refresh_history.click(select_video, video_picker, selection_outputs, concurrency_id=concurrency_id)

    def perform(video_id, url, api_key, model_id, instruction, count, tokens, force):
        try:
            record, cached = workspace.analyze(video_id, url, (api_key or "").strip() or os.getenv("VIDEO_LLM_API_KEY", ""),
                                               model_id, instruction, count, tokens, force)
            message = ("**命中本地缓存：未调用 API，无新增模型开销。**" if cached else
                       "**已复用保存的图检索证据，仅生成最终概括；结果已保存。**" if record["request"].get("reused_graph_trace_from") else
                       "**分析完成，结果已自动保存到本地历史。**")
            return (*presentation(record), gr.update(choices=history_choices(video_id), value=record["id"]), message)
        except (ValueError, OSError) as error:
            return (*[gr.update() for _ in result_outputs], gr.update(),
                    _model_feedback("error", "分析未完成", str(error),
                                    "已保留上次展示结果。若已有图检索证据，再次点击分析会复用证据；不会自动重试。"))

    inputs = [video_picker, endpoint, key, model, prompt, search_rounds, max_tokens]

    def save_connection(url, api_key, model_id):
        try:
            save_connection_environment(workspace.root, url, api_key, model_id)
        except ValueError as error:
            return gr.update(), _model_feedback("error", "连接设置未保存", str(error))
        except OSError:
            return gr.update(), _model_feedback("error", "连接设置未保存", "无法写入项目 .env，请检查项目目录的写入权限；环境变量未更新。")
        return gr.update(value=""), _model_feedback("success", "连接设置已保存", "已写入项目 .env 并更新服务环境变量。Key 不回显；留空即可继续使用，重启后自动读取。")

    save_connection_button.click(save_connection, [endpoint, key, model], [key, connection_status],
                                 concurrency_limit=1, concurrency_id=concurrency_id + "-settings")

    def fetch_models(url, api_key, current_model):
        try:
            effective_key = (api_key or "").strip() or os.getenv("VIDEO_LLM_API_KEY", "").strip()
            models = list_models(url, effective_key)
        except ModelCatalogError as error:
            return gr.update(), _model_feedback("error", str(error), error.detail, error.suggestion, error.url)
        except ValueError as error:
            return gr.update(), _model_feedback("error", str(error), suggestion="请修改连接设置后重试；已保留当前模型和列表。")
        except OSError:
            return gr.update(), _model_feedback("error", "网络读取失败", suggestion="请检查网络和系统代理后重试；已保留当前模型和列表。")
        current = (current_model or "").strip()
        chosen = current or (models[0] if models else None)
        message = (f"已获取 {len(models)} 个模型" if models else "接口返回的模型列表为空")
        detail = "请选择支持工具调用的文本模型。" if models else "请检查账号的模型授权，也可手动输入模型名。"
        if current and current not in models:
            detail += " 当前填写的模型未出现在列表中，已保留供手动使用。"
        return gr.update(choices=models, value=chosen), _model_feedback("success" if models else "info", message, detail)

    fetch_models_button.click(fetch_models, [endpoint, key, model], [model, model_list_status],
                              concurrency_limit=1, concurrency_id=concurrency_id + "-models", show_progress="minimal")

    def reset_model_list(current_model):
        return _model_feedback("info", "连接设置已更改，请重新获取模型列表。", "当前模型和上次列表已保留，也可直接手动输入模型名。")

    endpoint.input(reset_model_list, model, model_list_status, queue=False)
    key.input(reset_model_list, model, model_list_status, queue=False)

    def restore(run_id):
        if not run_id:
            raise gr.Error("请先选择一条 API 历史记录。")
        request = workspace.run(run_id)["request"]
        if not request:
            raise gr.Error("这条导入记录没有本机 API 调用参数。")
        if request.get("input_mode") != "scene_graph_tools":
            raise gr.Error("这条记录属于旧版画面分析，仅保留回放；请使用当前图检索设置。")
        return request["endpoint"], request["model"], request["prompt"], request["search_rounds"], request.get("max_tokens") or 0

    restore_settings.click(restore, selected_run, [endpoint, model, prompt, search_rounds, max_tokens])
    analyze_button.click(lambda *args: perform(*args, False), inputs, [*result_outputs, history, status],
                         concurrency_limit=1, concurrency_id=concurrency_id)
    force_button.click(lambda *args: perform(*args, True), inputs, [*result_outputs, history, status],
                       concurrency_limit=1, concurrency_id=concurrency_id)

    def import_result(video_id, path):
        if not path:
            raise gr.Error("请先选择结果 JSON。")
        try:
            record = workspace.import_result(video_id, path)
            return (*presentation(record), gr.update(choices=history_choices(video_id), value=record["id"]),
                    "**已保存导入结果，未调用 API。**")
        except (ValueError, OSError) as error:
            raise gr.Error(str(error)) from None

    import_button.click(import_result, [video_picker, result_file], [*result_outputs, history, status], concurrency_id=concurrency_id)

    def event_time(run_id, evt: gr.SelectData):
        if not run_id or evt.index is None:
            return gr.update(), gr.update()
        row = evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index
        records = workspace.run(run_id)["result"]["events"]
        if not 0 <= row < len(records):
            return gr.update(), gr.update()
        return records[row]["start_seconds"], gr.update(open=True)

    events.select(event_time, selected_run, [evidence_time, evidence_panel], concurrency_id=concurrency_id)

    def preview(video_id, seconds):
        video = workspace.video(video_id)
        cap = cv2.VideoCapture(video["path"])
        try:
            index = min(round(float(seconds) * video["fps"]), video["frames"] - 1)
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(index, 0))
            ok, image = cap.read()
            return cv2.cvtColor(image, cv2.COLOR_BGR2RGB) if ok else None
        finally:
            cap.release()

    evidence_time.change(preview, [video_picker, evidence_time], evidence_image, concurrency_id=concurrency_id)
    evidence_time.change(None, evidence_time, None, js="""(seconds) => {
        const video = document.querySelector('#analysis-video video');
        if (video && Number.isFinite(seconds)) { video.currentTime = seconds; video.pause(); }
    }""")
    return AnalysisPanel(selection_outputs, select_video)
