"""把 VideoGraph 写成 Neo4j Browser 可粘贴的 Cypher，以及完整 CSV。

Demo 页面本身用 NetworkX 画同一套属性图，不要求本机安装 Neo4j。
"""

from __future__ import annotations

import csv
from pathlib import Path


def _cypher(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{text}'"


def _select_tracks(tracks: list[dict], limit: int) -> list[dict]:
    primary = [track for track in tracks if not track.get("parent_track_id")]
    primary.sort(key=lambda track: -track["observation_count"])
    chosen = primary[:limit]
    if len(chosen) < limit:
        rest = [track for track in tracks if track.get("parent_track_id")]
        rest.sort(key=lambda track: -track["observation_count"])
        chosen.extend(rest[: limit - len(chosen)])
    return chosen


def export_neo4j(bundle: dict, output_dir: Path, export_cfg: dict) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    tracks = bundle["tracks"]
    relations = bundle["temporal_relations"]
    events = bundle["events"]
    clips = bundle["clips"]

    _write_csv(
        output_dir / "tracks.csv",
        ["track_id", "label", "status", "start_frame", "end_frame", "observations", "parent_track_id", "attributes"],
        [
            [
                track["track_id"],
                track["canonical_label"],
                track["status"],
                track["start_frame"],
                track["end_frame"],
                track["observation_count"],
                track.get("parent_track_id") or "",
                " | ".join(track.get("attributes") or []),
            ]
            for track in tracks
        ],
    )
    _write_csv(
        output_dir / "relations.csv",
        ["relation_id", "subject", "object", "predicate", "start_frame", "end_frame", "confidence"],
        [
            [
                relation["relation_id"],
                relation["subject_track_id"],
                relation["object_track_id"],
                relation["predicate"],
                relation["start_frame"],
                relation["end_frame"],
                relation["confidence"],
            ]
            for relation in relations
        ],
    )
    _write_csv(
        output_dir / "events.csv",
        ["event_id", "action", "subject", "object", "start_frame", "end_frame", "confidence", "source"],
        [
            [
                event["event_id"],
                event["action"],
                event["subject_track_id"],
                event["object_track_id"],
                event["start_frame"],
                event["end_frame"],
                event["confidence"],
                event["source"],
            ]
            for event in events
        ],
    )

    chosen = _select_tracks(tracks, int(export_cfg["neo4j_track_limit"]))
    chosen_ids = {track["track_id"] for track in chosen}
    min_span = int(export_cfg["neo4j_min_span"])
    min_conf = float(export_cfg["neo4j_min_confidence"])
    chosen_relations = [
        relation
        for relation in relations
        if relation["subject_track_id"] in chosen_ids
        and relation["object_track_id"] in chosen_ids
        and relation["end_frame"] - relation["start_frame"] + 1 >= min_span
        and relation["confidence"] >= min_conf
    ]
    chosen_relations.sort(key=lambda relation: -(relation["end_frame"] - relation["start_frame"] + 1) * relation["confidence"])
    chosen_relations = chosen_relations[: int(export_cfg["neo4j_relation_limit"])]
    chosen_events = [
        event
        for event in events
        if event["subject_track_id"] in chosen_ids and (not event["object_track_id"] or event["object_track_id"] in chosen_ids)
    ]
    chosen_events.sort(key=lambda event: (0 if event["source"] == "transition" else 1, -(event["end_frame"] - event["start_frame"])))
    chosen_events = chosen_events[: int(export_cfg["neo4j_event_limit"])]

    lines = [
        "// 层次化视频场景图属性图。在 Neo4j Browser 里整段执行。",
        "// 节点: Track / Clip / Event；关系: SCENE_RELATION / PART_OF / SUBJECT / OBJECT / COVERS",
        "// 这是便于展示的子图。完整表是同目录 CSV。",
        "",
    ]
    for track in chosen:
        attributes = " | ".join(track.get("attributes") or [])[:180]
        lines.append(
            "MERGE (t:Track {track_id: "
            + _cypher(track["track_id"])
            + "}) SET t.label = "
            + _cypher(track["canonical_label"])
            + ", t.status = "
            + _cypher(track["status"])
            + f", t.start_frame = {track['start_frame']}, t.end_frame = {track['end_frame']}"
            + f", t.observations = {track['observation_count']}, t.attributes = "
            + _cypher(attributes)
            + ";"
        )
    lines.append("")
    for track in chosen:
        parent = track.get("parent_track_id")
        if parent and parent in chosen_ids:
            lines.append(
                f"MATCH (c:Track {{track_id: {_cypher(track['track_id'])}}}), "
                f"(p:Track {{track_id: {_cypher(parent)}}}) MERGE (c)-[:PART_OF]->(p);"
            )
    lines.append("")
    for relation in chosen_relations:
        lines.append(
            "MATCH (a:Track {track_id: "
            + _cypher(relation["subject_track_id"])
            + "}), (b:Track {track_id: "
            + _cypher(relation["object_track_id"])
            + "}) MERGE (a)-[r:SCENE_RELATION {predicate: "
            + _cypher(relation["predicate"])
            + f", start_frame: {relation['start_frame']}, end_frame: {relation['end_frame']}"
            + "}]->(b) SET r.confidence = "
            + str(relation["confidence"])
            + ";"
        )
    lines.append("")
    for event in chosen_events:
        lines.append(
            "MERGE (e:Event {event_id: "
            + _cypher(event["event_id"])
            + "}) SET e.action = "
            + _cypher(event["action"])
            + f", e.start_frame = {event['start_frame']}, e.end_frame = {event['end_frame']}"
            + f", e.confidence = {event['confidence']}, e.source = "
            + _cypher(event["source"])
            + ";"
        )
        lines.append(
            "MATCH (e:Event {event_id: "
            + _cypher(event["event_id"])
            + "}), (s:Track {track_id: "
            + _cypher(event["subject_track_id"])
            + "}) MERGE (e)-[:SUBJECT]->(s);"
        )
        if event.get("object_track_id"):
            lines.append(
                "MATCH (e:Event {event_id: "
                + _cypher(event["event_id"])
                + "}), (o:Track {track_id: "
                + _cypher(event["object_track_id"])
                + "}) MERGE (e)-[:OBJECT]->(o);"
            )
    lines.append("")
    for clip in clips:
        lines.append(
            "MERGE (c:Clip {clip_id: "
            + _cypher(clip["clip_id"])
            + "}) SET c.start_frame = "
            + str(clip["start_frame"])
            + ", c.end_frame = "
            + str(clip["end_frame"])
            + ", c.summary = "
            + _cypher(clip["summary"][:240])
            + ";"
        )
        linked = 0
        for track_id in clip["track_ids"]:
            if track_id not in chosen_ids:
                continue
            lines.append(
                "MATCH (c:Clip {clip_id: "
                + _cypher(clip["clip_id"])
                + "}), (t:Track {track_id: "
                + _cypher(track_id)
                + "}) MERGE (c)-[:COVERS]->(t);"
            )
            linked += 1
            if linked >= 8:
                break

    cypher_path = output_dir / "browser.cypher"
    cypher_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return cypher_path


def _write_csv(path: Path, header: list[str], rows: list[list]):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
