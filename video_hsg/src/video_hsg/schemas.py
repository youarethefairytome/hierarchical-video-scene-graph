"""流水线内部数据结构。写出的 JSON 在 pipeline 里单独组装。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FrameEntity:
    frame_id: int
    local_index: int
    local_name: str
    label: str
    canonical_label: str
    bbox: list[float]
    score: float
    attribute_text: str | None = None
    parent_local_name: str | None = None
    child_local_names: list[str] = field(default_factory=list)
    parent_canonical: str | None = None
    child_canonicals: list[str] = field(default_factory=list)
    attr_tokens: set[str] = field(default_factory=set)
    relation_signature: set[tuple[str, str]] = field(default_factory=set)
    track_id: str | None = None


@dataclass
class FrameRelation:
    frame_id: int
    subject_index: int
    object_index: int
    subject_local_name: str
    object_local_name: str
    predicate_raw: str
    predicate_norm: str
    source: str
    subject_track_id: str | None = None
    object_track_id: str | None = None


@dataclass
class FrameGraph:
    frame_id: int
    source_frame: int
    key: str
    image_path: str
    width: int
    height: int
    entities: list[FrameEntity]
    relations: list[FrameRelation]


@dataclass
class Observation:
    frame_id: int
    local_index: int
    local_name: str
    bbox: list[float]
    score: float
    attribute_text: str | None
    match_score: float | None


@dataclass
class EntityTrack:
    track_id: str
    canonical_label: str
    raw_label: str
    status: str
    start_frame: int
    end_frame: int
    observations: list[Observation]
    missed_count: int = 0
    hits: int = 0
    attributes: list[str] = field(default_factory=list)
    parent_track_id: str | None = None
    parent_canonical: str | None = None
    child_canonicals: frozenset[str] = field(default_factory=frozenset)
    relation_signature: frozenset[tuple[str, str]] = field(default_factory=frozenset)
    recent_attr_tokens: set[str] = field(default_factory=set)
    attr_history: list[set[str]] = field(default_factory=list)
