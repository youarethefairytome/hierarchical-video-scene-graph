"""视频问答、图证据和全视频节点浏览。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

import gradio as gr
import pandas as pd

from analysis_tab import _model_feedback
from ui_theme import panel_heading
from video_hsg.question_answering import VideoQuestionService

NODE_COLUMNS = ["节点 ID", "类型", "名称 / 描述", "开始（秒）", "结束（秒）"]
KIND_NAMES = {"entity": "实体轨迹", "relation": "关系", "event": "事件", "clip": "片段", "frame": "帧级图"}


@dataclass
class QuestionPanel:
    selection_outputs: list
    select_video: Callable


def build_question_tab(workspace, video_picker, analysis_panel, *, concurrency_id="video-workspace"):
    service = VideoQuestionService(workspace)

    def context_text(video_id, run_id=None):
        try:
            return service.context_notice(video_id, run_id)
        except (ValueError, OSError) as error:
            return str(error)

    def node_page(video_id, text, kind, page):
        try:
            result = service.browse_nodes(video_id, text or "", kind, page)
            rows = []
            for node in result["nodes"]:
                label = node.get("canonical_label") or node.get("summary")
                if not label:
                    label = " · ".join(str(node.get(k, "")) for k in ("subject_label", "predicate", "action", "object_label") if node.get(k))
                rows.append([node["node_id"], KIND_NAMES[node["kind"]], label,
                             node.get("start_seconds"), node.get("end_seconds")])
            message = f"全视频匹配 {result['total']} 个节点 · 第 {result['page']} / {result['pages']} 页，每页最多 10 条。"
            return pd.DataFrame(rows, columns=NODE_COLUMNS), result["page"], message
        except (ValueError, OSError) as error:
            return pd.DataFrame(columns=NODE_COLUMNS), 1, str(error)

    initial_id = video_picker.value
    initial_rows, initial_page, initial_status = node_page(initial_id, "", "all", 1)
    gr.HTML('<div class="analysis-intro"><h2>视频问答</h2><p>围绕当前视频提问，按需检索整段视频的节点与关系。</p></div>')
    context_notice = gr.Markdown(context_text(initial_id), elem_id="qa-context")
    with gr.Row(elem_classes="qa-layout"):
        with gr.Column(scale=6, min_width=360, elem_classes="surface-card"):
            gr.HTML(panel_heading("insight", "围绕视频连续追问", "使用视频理解页的模型设置，已有整段分析自动加入上下文"))
            chatbot = gr.Chatbot(value=[], height=450, label="当前视频问答", buttons=["copy", "copy_all"],
                                 placeholder="例如：主要人物与哪些物体发生了关系？请给出节点和时间证据。",
                                 sanitize_html=True, allow_tags=False, allow_file_downloads=False)
            question = gr.Textbox(label="你的问题", placeholder="输入问题，按 Enter 发送；可继续追问同一个实体或事件。", lines=2)
            with gr.Row():
                ask_button = gr.Button("发送问题", variant="primary")
                clear_button = gr.Button("清空当前对话")
            qa_status = gr.HTML(_model_feedback("info", "等待提问", "回答根据已有图数据生成，近 8 轮对话用于理解连续追问。"))
            with gr.Accordion("本轮图检索证据", open=False):
                qa_trace = gr.JSON(value=[], label="问答查询与返回节点")
        with gr.Column(scale=5, min_width=350, elem_classes="surface-card"):
            gr.HTML(panel_heading("entity", "全视频节点查询", "不限于当前帧，浏览和查看节点详情无需调用模型"))
            node_query = gr.Textbox(label="节点关键词 / 编号", placeholder="例如 person、holding、track_00002；留空可列举全部")
            node_kind = gr.Dropdown(choices=[("全部图节点", "all"), *[(label, value) for value, label in KIND_NAMES.items()]],
                                    value="all", label="节点类型")
            with gr.Row():
                page = gr.Number(value=initial_page, minimum=1, precision=0, label="页码")
                search = gr.Button("查询节点")
                previous = gr.Button("上一页", size="sm")
                following = gr.Button("下一页", size="sm")
            node_rows = gr.Dataframe(value=initial_rows, interactive=False, wrap=True,
                                     label="全视频节点列表（点击一行查看详情）", max_height=340)
            node_status = gr.Markdown(initial_status)
            with gr.Row():
                node_id = gr.Textbox(label="查看节点 ID", placeholder="track_00002 / rel_00001 / event_00001 / frame:4")
                neighbor_offset = gr.Number(value=0, minimum=0, precision=0, label="详情起始位置（每页 15 条）")
            inspect = gr.Button("查看节点详情", size="sm")
            node_detail = gr.JSON(value={}, label="节点属性、部件及相邻关系")
    chat_state = gr.State({})
    node_origin = gr.State(initial_id)

    def chat_messages(state):
        messages = []
        for turn in state.get("turns", []):
            messages.append({"role": "user", "content": turn["question"]})
            refs = "\n\n图节点：" + "、".join(f"`{i}`" for i in turn["node_ids"]) if turn["node_ids"] else ""
            messages.append({"role": "assistant", "content": turn["answer"] + refs})
        return messages

    def ask_video_question(video_id, text, state, run_id, url, api_key, model_id, rounds, tokens):
        try:
            record, state, cached = service.answer(video_id, text, state,
                endpoint=(url or "").strip() or os.getenv("VIDEO_LLM_BASE_URL", ""),
                key=(api_key or "").strip() or os.getenv("VIDEO_LLM_API_KEY", ""),
                model=(model_id or "").strip() or os.getenv("VIDEO_LLM_MODEL", ""),
                search_rounds=rounds, max_tokens=tokens, selected_run=run_id)
            message = "已读取本地问答缓存，未调用模型。" if cached else "回答已保存，可在本轮检索证据中核对节点。"
            return chat_messages(state), state, "", _model_feedback("success", message), record["evidence"], context_text(video_id, run_id)
        except (ValueError, OSError) as error:
            return gr.update(), gr.update(), gr.update(), _model_feedback("error", "问答未完成", str(error)), gr.update(), context_text(video_id, run_id)

    chat_outputs = [chatbot, chat_state, question, qa_status, qa_trace, context_notice]
    chat_inputs = [video_picker, question, chat_state, analysis_panel.selected_run, *analysis_panel.settings_inputs]
    ask_button.click(ask_video_question, chat_inputs, chat_outputs, concurrency_id=concurrency_id)
    question.submit(ask_video_question, chat_inputs, chat_outputs, concurrency_id=concurrency_id)

    def clear_video_chat():
        return [], {}, "", _model_feedback("info", "当前对话已清空", "已有整段分析和问答缓存仍保留。"), []
    clear_button.click(clear_video_chat, None, [chatbot, chat_state, question, qa_status, qa_trace], concurrency_id=concurrency_id)
    analysis_panel.selected_run.change(context_text, [video_picker, analysis_panel.selected_run], context_notice, concurrency_id=concurrency_id)

    def browse_video_nodes(video_id, text, kind, page_value):
        return (*node_page(video_id, text, kind, page_value), video_id)

    browse_outputs = [node_rows, page, node_status, node_origin]
    search.click(browse_video_nodes, [video_picker, node_query, node_kind, page], browse_outputs, concurrency_id=concurrency_id)
    node_query.submit(browse_video_nodes, [video_picker, node_query, node_kind, page], browse_outputs, concurrency_id=concurrency_id)
    previous.click(lambda v, q, k, p: browse_video_nodes(v, q, k, max(1, int(p or 1) - 1)),
                   [video_picker, node_query, node_kind, page], browse_outputs, concurrency_id=concurrency_id)
    following.click(lambda v, q, k, p: browse_video_nodes(v, q, k, int(p or 1) + 1),
                    [video_picker, node_query, node_kind, page], browse_outputs, concurrency_id=concurrency_id)

    def inspect_video_node(video_id, identifier, offset):
        try:
            return service.inspect_node(video_id, identifier, offset), "已读取当前视频的节点详情。"
        except (ValueError, OSError) as error:
            return {}, str(error)
    inspect.click(inspect_video_node, [video_picker, node_id, neighbor_offset], [node_detail, node_status], concurrency_id=concurrency_id)

    def select_node(video_id, origin_video, evt: gr.SelectData):
        row = evt.row_value
        if video_id != origin_video or not row:
            return gr.update(), gr.update(), gr.update(), gr.update()
        identifier = row.get(NODE_COLUMNS[0]) if isinstance(row, dict) else row[0]
        detail, message = inspect_video_node(video_id, identifier, 0)
        return identifier, 0, detail, message
    node_rows.select(select_node, [video_picker, node_origin], [node_id, neighbor_offset, node_detail, node_status], concurrency_id=concurrency_id)

    def select_video(video_id):
        rows, current_page, message = node_page(video_id, "", "all", 1)
        return (context_text(video_id), [], {}, "", _model_feedback("info", "等待提问"), [],
                "", "all", current_page, rows, message, "", 0, {}, video_id)
    outputs = [context_notice, chatbot, chat_state, question, qa_status, qa_trace,
               node_query, node_kind, page, node_rows, node_status, node_id, neighbor_offset, node_detail, node_origin]
    return QuestionPanel(outputs, select_video)
