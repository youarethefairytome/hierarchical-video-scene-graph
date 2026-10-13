"""类别和谓词归一化。只使用显式别名，避免把 glass、pants 这类词切坏。"""

from __future__ import annotations

import re

LABEL_ALIASES = {
    "man": "person",
    "woman": "person",
    "boy": "person",
    "girl": "person",
    "pedestrian": "person",
    "people": "person",
    "human": "person",
    "windows": "window",
    "buildings": "building",
    "trees": "tree",
    "doors": "door",
    "wheels": "wheel",
    "chairs": "chair",
    "poles": "pole",
    "walls": "wall",
    "tires": "tire",
    "handlebars": "handlebar",
    "lamp post": "pole",
    "lamppost": "pole",
    "light pole": "pole",
    "streetlight": "street light",
    "street lamp": "street light",
    "sidewalk": "pavement",
    "sofa": "couch",
    "television": "tv",
}

RELATION_ALIASES = {
    "beside": "near",
    "next to": "near",
    "adjacent to": "near",
    "close to": "near",
    "bordering": "near",
    "borders": "near",
    "against": "near",
    "parallel to": "near",
    "on top of": "on",
    "resting on": "on",
    "located on": "on",
    "mounted on": "on",
    "standing on": "on",
    "part of": "part_of",
    "part_of": "part_of",
    "is part of": "part_of",
    "has": "has",
    "have": "has",
    "having": "has",
    "contains": "has",
    "containing": "has",
    "housing": "has",
    "supporting": "supports",
    "supports": "supports",
    "attached to": "attached_to",
    "hanging from": "attached_to",
    "in front of": "in_front_of",
    "parked in front of": "in_front_of",
    "under": "below",
    "underneath": "below",
    "walking past": "walking_past",
    "leading to": "leading_to",
}

STOPWORDS = {
    "a",
    "an",
    "the",
    "of",
    "with",
    "in",
    "on",
    "and",
    "to",
    "for",
    "from",
    "at",
    "by",
    "it",
    "its",
}

DYNAMIC_PREDICATES = {
    "wearing",
    "holding",
    "touching",
    "walking_past",
    "parked",
    "illuminating",
    "displaying",
}

TRANSITION_PATTERNS = (
    (("near", "touching", "holding"), "pick_up"),
    (("near", "holding"), "pick_up"),
    (("holding", "touching", "near"), "put_down"),
    (("holding", "near"), "put_down"),
    (("near", "on"), "move_onto"),
    (("above", "on"), "placed_on"),
)


def canonical_label(text: str | None) -> str:
    raw = (text or "").strip().lower().replace("_", " ")
    raw = re.sub(r"[^a-z0-9\s\-/]", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    if not raw:
        return "unknown"
    return LABEL_ALIASES.get(raw, raw)


def normalize_predicate(text: str | None) -> str:
    raw = re.sub(r"\s+", " ", (text or "").strip().lower())
    if not raw:
        return "related_to"
    if raw in RELATION_ALIASES:
        return RELATION_ALIASES[raw]
    return raw.replace(" ", "_")


def attribute_tokens(text: str | None) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {word for word in words if word not in STOPWORDS and len(word) > 1}
