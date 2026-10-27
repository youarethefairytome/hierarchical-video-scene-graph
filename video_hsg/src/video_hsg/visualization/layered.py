"""把一帧 HSG 排成示例那种五层：场景、实体、部件、属性、关系。"""

from __future__ import annotations

FAMILIES = ("#3b6ea5", "#a86432", "#d64545", "#2f8f6b", "#c47b00", "#7a4ea3")


def _children(frame: dict):
    by_name = {entity["local_name"]: entity for entity in frame["entities"]}
    children: dict[str, list[dict]] = {}
    roots: list[dict] = []
    for entity in frame["entities"]:
        parent = entity.get("parent_local_name")
        if parent and parent in by_name and parent != entity["local_name"]:
            children.setdefault(parent, []).append(entity)
        else:
            roots.append(entity)
    for kids in children.values():
        kids.sort(key=lambda item: -float(item["score"]))
    roots.sort(key=lambda item: -float(item["score"]))
    return by_name, children, roots


def _detail(title: str, lines: list[str]) -> dict:
    return {"title": title, "lines": [line for line in lines if line]}


def _attr_label(entity: dict) -> str:
    text = (entity.get("attribute_text") or "").strip()
    if not text:
        return ""
    words = text.split()[:6]
    return f"{entity['canonical_label']}: {' '.join(words)}"


def _node(node_id: str, layer: int, label: str, x: float, z: float, color: str, shape: str, detail: dict) -> dict:
    return {
        "id": node_id,
        "layer": layer,
        "label": label,
        "x": round(x, 3),
        "z": round(z, 3),
        "color": color,
        "shape": shape,
        "detail": detail,
    }


def _spread(count: int, gap: float) -> list[float]:
    if count <= 0:
        return []
    origin = -(count - 1) * gap / 2
    return [origin + index * gap for index in range(count)]


def build_layered_scene(frame: dict) -> dict:
    _by_name, children, roots = _children(frame)
    nodes: list[dict] = []
    edges: list[dict] = []
    placed: dict[str, str] = {}
    columns: list[tuple[dict, list[dict], float]] = []
    cursor = 0.0
    for root in roots:
        parts = children.get(root["local_name"], [])
        width = max(1.15, (len(parts) - 1) * 1.05)
        columns.append((root, parts, cursor + width / 2))
        cursor += width + 1.35
    center_shift = cursor / 2 if columns else 0.0

    nodes.append(
        _node(
            "scene",
            0,
            f"frame {frame['frame_id']}",
            0,
            0,
            "#3b6ea5",
            "orb",
            _detail(
                f"采样帧 {frame['frame_id']}",
                [
                    "层: L0 场景",
                    f"原始帧: {frame['source_frame']}",
                    f"实体数: {len(frame['entities'])}",
                    f"关系数: {len(frame['relations'])}",
                ],
            ),
        )
    )

    for index, (root, parts, column_x) in enumerate(columns):
        color = FAMILIES[index % len(FAMILIES)]
        root_id = "e-" + root["local_name"]
        x = column_x - center_shift
        nodes.append(
            _node(
                root_id,
                1,
                root["local_name"],
                x,
                0.15 if index % 2 else -0.15,
                color,
                "orb",
                _detail(
                    root["local_name"],
                    [
                        "层: L1 实体",
                        f"类别: {root['canonical_label']}",
                        f"轨迹: {root.get('track_id') or '-'}",
                        f"置信度: {float(root['score']):.2f}",
                        f"属性: {(root.get('attribute_text') or '-')[:120]}",
                    ],
                ),
            )
        )
        placed[root["local_name"]] = root_id
        edges.append({"source": "scene", "target": root_id, "color": color, "dash": True})

        part_offsets = _spread(len(parts), 1.05)
        for part_index, part in enumerate(parts):
            part_id = "p-" + part["local_name"]
            px = x + part_offsets[part_index]
            nodes.append(
                _node(
                    part_id,
                    2,
                    part["local_name"],
                    px,
                    0.85,
                    color,
                    "orb",
                    _detail(
                        part["local_name"],
                        [
                            "层: L2 部件",
                            f"属于: {root['local_name']}",
                            f"类别: {part['canonical_label']}",
                            f"轨迹: {part.get('track_id') or '-'}",
                            f"置信度: {float(part['score']):.2f}",
                            f"属性: {(part.get('attribute_text') or '-')[:120]}",
                        ],
                    ),
                )
            )
            placed[part["local_name"]] = part_id
            edges.append({"source": root_id, "target": part_id, "color": color, "dash": False})

        carriers = [root, *parts]
        for carrier in carriers:
            label = _attr_label(carrier)
            if not label:
                continue
            host_id = placed[carrier["local_name"]]
            host = next(item for item in nodes if item["id"] == host_id)
            attr_id = "a-" + carrier["local_name"]
            nodes.append(
                _node(
                    attr_id,
                    3,
                    label,
                    host["x"],
                    host["z"] + 0.15,
                    color,
                    "card",
                    _detail(label, ["层: L3 属性", f"实体: {carrier['local_name']}", carrier.get("attribute_text") or ""]),
                )
            )
            edges.append({"source": host_id, "target": attr_id, "color": color, "dash": True})

    relation_slots: dict[str, int] = {}
    kept = 0
    for relation in frame["relations"]:
        subject_name = relation["subject_local_name"]
        subject_id = placed.get(subject_name)
        subject = next((item for item in nodes if item["id"] == subject_id), None) if subject_id else None
        slot = relation_slots.get(subject_name, 0)
        relation_slots[subject_name] = slot + 1
        relation_id = f"r-{kept}"
        predicate = relation["predicate"]
        anchor_x = subject["x"] if subject else (kept - len(frame["relations"]) / 2) * 0.9
        anchor_z = subject["z"] if subject else 0.0
        nodes.append(
            _node(
                relation_id,
                4,
                predicate,
                anchor_x + (slot - (relation_slots[subject_name] - 1) / 2) * 0.8,
                anchor_z + 0.35,
                "#6d5bd0",
                "card",
                _detail(
                    predicate,
                    [
                        "层: L4 关系",
                        f"{relation['subject_local_name']} → {relation['object_local_name']}",
                        f"谓词: {predicate}",
                        f"主体轨迹: {relation.get('subject_track_id') or '-'}",
                        f"客体轨迹: {relation.get('object_track_id') or '-'}",
                    ],
                ),
            )
        )
        if subject_id:
            edges.append({"source": subject_id, "target": relation_id, "color": "#6d5bd0", "dash": True})
        object_name = relation["object_local_name"]
        if subject_id and object_name in placed and object_name != subject_name and relation["predicate"] in {"near", "has", "on", "part_of"}:
            edges.append(
                {
                    "source": subject_id,
                    "target": placed[object_name],
                    "color": "#8aa0b8",
                    "dash": True,
                }
            )
        kept += 1

    return {
        "title": f"采样帧 {frame['frame_id']}  ·  原始帧 {frame['source_frame']}",
        "nodes": nodes,
        "edges": edges,
    }
