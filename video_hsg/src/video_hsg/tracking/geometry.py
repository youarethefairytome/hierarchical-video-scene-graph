"""框几何：IoU、中心距离、尺度比。"""

from __future__ import annotations

import math

import numpy as np


def pairwise_iou(boxes_a: np.ndarray, boxes_b: np.ndarray) -> np.ndarray:
    if len(boxes_a) == 0 or len(boxes_b) == 0:
        return np.zeros((len(boxes_a), len(boxes_b)), dtype=np.float32)
    top_left = np.maximum(boxes_a[:, None, :2], boxes_b[None, :, :2])
    bottom_right = np.minimum(boxes_a[:, None, 2:], boxes_b[None, :, 2:])
    wh = np.clip(bottom_right - top_left, 0, None)
    inter = wh[:, :, 0] * wh[:, :, 1]
    area_a = np.clip(boxes_a[:, 2] - boxes_a[:, 0], 0, None) * np.clip(boxes_a[:, 3] - boxes_a[:, 1], 0, None)
    area_b = np.clip(boxes_b[:, 2] - boxes_b[:, 0], 0, None) * np.clip(boxes_b[:, 3] - boxes_b[:, 1], 0, None)
    union = area_a[:, None] + area_b[None, :] - inter
    return (inter / np.clip(union, 1e-6, None)).astype(np.float32)


def pairwise_center(boxes_a: np.ndarray, boxes_b: np.ndarray, width: int, height: int, sigma: float):
    center_ax = (boxes_a[:, 0] + boxes_a[:, 2]) * 0.5
    center_ay = (boxes_a[:, 1] + boxes_a[:, 3]) * 0.5
    center_bx = (boxes_b[:, 0] + boxes_b[:, 2]) * 0.5
    center_by = (boxes_b[:, 1] + boxes_b[:, 3]) * 0.5
    dx = center_ax[:, None] - center_bx[None, :]
    dy = center_ay[:, None] - center_by[None, :]
    diagonal = math.hypot(width, height) or 1.0
    distance = np.sqrt(dx * dx + dy * dy) / diagonal
    similarity = np.exp(-distance / max(float(sigma), 1e-6))
    return distance.astype(np.float32), similarity.astype(np.float32)


def pairwise_size(boxes_a: np.ndarray, boxes_b: np.ndarray) -> np.ndarray:
    if len(boxes_a) == 0 or len(boxes_b) == 0:
        return np.zeros((len(boxes_a), len(boxes_b)), dtype=np.float32)
    area_a = np.clip(boxes_a[:, 2] - boxes_a[:, 0], 0, None) * np.clip(boxes_a[:, 3] - boxes_a[:, 1], 0, None)
    area_b = np.clip(boxes_b[:, 2] - boxes_b[:, 0], 0, None) * np.clip(boxes_b[:, 3] - boxes_b[:, 1], 0, None)
    area_a = np.clip(area_a, 1e-6, None)
    area_b = np.clip(area_b, 1e-6, None)
    small = np.minimum(area_a[:, None], area_b[None, :])
    large = np.maximum(area_a[:, None], area_b[None, :])
    return (small / large).astype(np.float32)
