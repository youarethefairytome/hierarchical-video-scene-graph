"""帧框、层次场景图、Clip/Video 图和轨迹时间线。"""

from __future__ import annotations

import colorsys
import hashlib
import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
from matplotlib import font_manager
from PIL import Image, ImageDraw, ImageFont

_FONT_PATH = Path(r"C:\Windows\Fonts\msyh.ttc")
if _FONT_PATH.exists():
    font_manager.fontManager.addfont(str(_FONT_PATH))
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False


def color_for(key: str) -> tuple[int, int, int]:
    digest = hashlib.md5((key or "none").encode("utf-8")).hexdigest()
    hue = int(digest[:2], 16) / 255
    red, green, blue = colorsys.hsv_to_rgb(hue, 0.62, 0.98)
    return int(red * 255), int(green * 255), int(blue * 255)


def _mpl_color(key: str) -> tuple[float, float, float]:
    red, green, blue = color_for(key)
    return red / 255, green / 255, blue / 255


def _font(size: int):
    if _FONT_PATH.exists():
        return ImageFont.truetype(str(_FONT_PATH), size)
    return ImageFont.load_default()


def _short(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."


def figure_to_image(fig) -> Image.Image:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight")
    plt.close(fig)
    buffer.seek(0)
    image = Image.open(buffer)
    image.load()
    return image.convert("RGB")


def message_image(text: str, size=(960, 540)) -> Image.Image:
    image = Image.new("RGB", size, (248, 248, 246))
    draw = ImageDraw.Draw(image)
    draw.text((36, size[1] // 2 - 20), text, fill=(40, 40, 40), font=_font(28))
    return image


def visible_entities(frame: dict, show_parts: bool, highlight: set[str]) -> list[dict]:
    entities = frame["entities"]
    if show_parts:
        return entities
    kept = [
        entity
        for entity in entities
        if not entity.get("parent_local_name") or entity.get("track_id") in highlight
    ]
    return kept or entities


def render_frame(
    frame: dict,
    show_parts: bool,
    highlight: set[str],
    base: Image.Image | None = None,
    show_boxes: bool = True,
) -> Image.Image:
    width = int(frame["width"])
    height = int(frame["height"])
    if base is None:
        canvas = Image.new("RGB", (width, height), (22, 24, 30))
        scale_x = scale_y = 1.0
    else:
        canvas = base.convert("RGB")
        scale_x = canvas.width / max(width, 1)
        scale_y = canvas.height / max(height, 1)
    draw = ImageDraw.Draw(canvas)
    font = _font(18)
    small = _font(14)
    entities = visible_entities(frame, show_parts, highlight) if show_boxes else []
    for entity in entities:
        x1, y1, x2, y2 = entity["bbox"]
        box = [x1 * scale_x, y1 * scale_y, x2 * scale_x, y2 * scale_y]
        key = entity.get("track_id") or entity["canonical_label"]
        color = color_for(key)
        selected = entity.get("track_id") in highlight
        width_px = 6 if selected else 3
        draw.rectangle(box, outline=color, width=width_px)
        if (box[3] - box[1]) < 22 and not selected:
            continue
        tag = entity["canonical_label"]
        if entity.get("track_id"):
            tag += " " + entity["track_id"][-4:]
        tag = _short(tag, 24)
        text_box = draw.textbbox((box[0], box[1]), tag, font=small if not selected else font)
        draw.rectangle(text_box, fill=color)
        draw.text((box[0], box[1]), tag, fill=(12, 12, 12), font=small if not selected else font)

    if show_boxes or base is None:
        title = f"采样帧 {frame['frame_id']}  原始帧 {frame['source_frame']}"
        if show_boxes:
            title += f"  显示 {len(entities)}/{len(frame['entities'])}"
        banner = _font(22)
        draw.rectangle([0, 0, canvas.width, 36], fill=(10, 10, 14))
        draw.text((12, 6), title, fill=(235, 235, 235), font=banner)
    if canvas.width > 1100:
        scale = 1100 / canvas.width
        canvas = canvas.resize((1100, int(canvas.height * scale)), Image.Resampling.LANCZOS)
    return canvas


def _cap(entities: list[dict], highlight: set[str], limit: int) -> list[dict]:
    pinned = [entity for entity in entities if entity.get("track_id") in highlight]
    rest = [entity for entity in entities if entity not in pinned]
    rest.sort(key=lambda entity: -float(entity["score"]))
    return pinned + rest[: max(0, limit - len(pinned))]



def render_frame_graph(frame: dict, show_parts: bool, highlight: set[str]) -> Image.Image:
    entities = _cap(visible_entities(frame, show_parts, highlight), highlight, 28)
    if not entities:
        return message_image("这一帧没有可显示的实体")
    by_index = {entity["local_index"]: entity for entity in entities}
    fig, ax = plt.subplots(figsize=(8.2, 7.2), dpi=120)
    for relation in frame["relations"]:
        if relation["subject_index"] not in by_index or relation["object_index"] not in by_index:
            continue
        subject = by_index[relation["subject_index"]]
        obj = by_index[relation["object_index"]]
        x1 = (subject["bbox"][0] + subject["bbox"][2]) / 2
        y1 = (subject["bbox"][1] + subject["bbox"][3]) / 2
        x2 = (obj["bbox"][0] + obj["bbox"][2]) / 2
        y2 = (obj["bbox"][1] + obj["bbox"][3]) / 2
        ax.annotate(
            "",
            xy=(x2, y2),
            xytext=(x1, y1),
            arrowprops={"arrowstyle": "->", "color": "#8a8f98", "lw": 1.0},
        )
        ax.text((x1 + x2) / 2, (y1 + y2) / 2, relation["predicate"], fontsize=7, color="#333333")
    for entity in entities:
        x = (entity["bbox"][0] + entity["bbox"][2]) / 2
        y = (entity["bbox"][1] + entity["bbox"][3]) / 2
        key = entity.get("track_id") or entity["canonical_label"]
        ax.scatter([x], [y], s=80 if entity.get("track_id") in highlight else 46, c=[_mpl_color(key)], zorder=3)
        ax.text(x, y, _short(entity["local_name"], 18), fontsize=7, ha="left", va="bottom")
    ax.set_xlim(0, frame["width"])
    ax.set_ylim(frame["height"], 0)
    ax.set_title(f"当前帧层次场景图  #{frame['frame_id']}")
    ax.set_xlabel("图像 x")
    ax.set_ylabel("图像 y")
    fig.tight_layout()
    return figure_to_image(fig)


def _runs(frame_ids: list[int]) -> list[tuple[int, int]]:
    if not frame_ids:
        return []
    ordered = sorted(frame_ids)
    start = previous = ordered[0]
    runs = []
    for frame_id in ordered[1:]:
        if frame_id == previous + 1:
            previous = frame_id
            continue
        runs.append((start, previous))
        start = previous = frame_id
    runs.append((start, previous))
    return runs


def select_timeline_tracks(tracks: list[dict], highlight: set[str], limit: int = 16) -> list[dict]:
    by_id = {track["track_id"]: track for track in tracks}
    chosen: list[dict] = []
    for track_id in highlight:
        track = by_id.get(track_id)
        if track and track not in chosen:
            chosen.append(track)
    rest = sorted(
        tracks,
        key=lambda track: -(track["observation_count"] * (0.45 if track.get("parent_track_id") else 1)),
    )
    for track in rest:
        if track not in chosen:
            chosen.append(track)
        if len(chosen) >= limit:
            break
    return chosen[:limit]


def render_timeline(tracks: list[dict], frame_id: int, clip: dict | None, highlight: set[str], frame_count: int) -> Image.Image:
    chosen = select_timeline_tracks(tracks, highlight)
    if not chosen:
        return message_image("还没有轨迹")
    fig, ax = plt.subplots(figsize=(11.2, 4.8), dpi=120)
    for index, track in enumerate(chosen):
        color = _mpl_color(track["track_id"])
        for start, end in _runs(track["frame_ids"]):
            ax.barh(index, end - start + 1, left=start, height=0.62, color=color, alpha=0.9)
    if clip:
        ax.axvspan(clip["start_frame"], clip["end_frame"], color="#f4c95d", alpha=0.18, label="当前 Clip")
    ax.axvline(frame_id, color="#c0392b", lw=1.4)
    labels = [f"{track['track_id']} {track['canonical_label']}" for track in chosen]
    ax.set_yticks(range(len(chosen)))
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlim(0, max(frame_count - 1, 1))
    ax.set_xlabel("采样帧")
    ax.set_title("轨迹时间线（红线是当前帧，色带是当前 Clip）")
    ax.invert_yaxis()
    fig.tight_layout()
    return figure_to_image(fig)


def render_link_graph(title: str, nodes: list[dict], edges: list[dict]) -> Image.Image:
    if not nodes:
        return message_image("这个窗口没有足够的轨迹")
    graph = nx.DiGraph()
    for node in nodes:
        graph.add_node(node["id"])
    for edge in edges:
        if edge["source"] in graph and edge["target"] in graph and edge["source"] != edge["target"]:
            graph.add_edge(edge["source"], edge["target"], label=edge["label"])
    if len(graph) == 1:
        pos = {nodes[0]["id"]: (0.0, 0.0)}
    else:
        pos = nx.spring_layout(graph, seed=7, k=1.8 / max(len(graph), 1) ** 0.5)
    fig, ax = plt.subplots(figsize=(8.2, 7.0), dpi=120)
    nx.draw_networkx_edges(graph, pos, ax=ax, arrows=True, arrowsize=12, edge_color="#9aa0a6", width=1.1, alpha=0.85)
    colors = [_mpl_color(node["color_key"]) for node in nodes if node["id"] in graph]
    nx.draw_networkx_nodes(graph, pos, ax=ax, node_color=colors, node_size=520)
    nx.draw_networkx_labels(
        graph,
        pos,
        labels={node["id"]: node["text"] for node in nodes},
        font_size=7,
        ax=ax,
    )
    edge_labels = {(u, v): data["label"] for u, v, data in graph.edges(data=True)}
    if len(edge_labels) <= 36:
        nx.draw_networkx_edge_labels(graph, pos, edge_labels=edge_labels, font_size=7, ax=ax)
    ax.set_title(title)
    ax.axis("off")
    fig.tight_layout()
    return figure_to_image(fig)
