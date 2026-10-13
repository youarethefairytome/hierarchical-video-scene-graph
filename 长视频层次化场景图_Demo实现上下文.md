# 面向长视频理解的层次化视频场景图 —— Demo 实现上下文

> 用途：作为后续实际编码、让 AI 编程助手接手项目、拆分任务和检查实现是否偏题的统一上下文。  
> 当前阶段目标不是重新复现/重跑 HSGG，而是利用已经生成的单帧 HSG JSON，完成 **跨帧实体关联 → TrackGraph → ClipGraph → VideoGraph → Event/Query → Demo**。

---

## 0. 一句话目标

把已经存在的单帧层次场景图：

```text
Frame HSG
= objects + hierarchy + attributes + relations
```

扩展为：

```text
Video
  ↓
FrameGraph
  ↓
Cross-frame Entity Association
  ↓
TrackGraph
  ↓
Temporal Relation Aggregation
  ↓
ClipGraph
  ↓
VideoGraph
  ↓
Event Index / Query
  ↓
Interactive Demo
```

最终 Demo 应做到：

1. 能打开/选择一段预处理视频或场景；
2. 能查看当前帧的 HSG；
3. 能看到同一实体跨帧被赋予稳定的 `track_id`；
4. 能查看某个局部窗口的 `ClipGraph`；
5. 能查看整段视频的 `VideoGraph`；
6. 能按人物、物体、动作或关系查询事件；
7. 点击查询结果时能定位到对应帧/时间区间。

---

# 1. 项目边界

## 1.1 课程项目最终要求

项目主题：

> 面向长视频理解的层次化视频场景图生成

核心要求：

- 视频帧采样；
- 目标检测与跟踪；
- 实体识别；
- 关系识别；
- 时序场景图构建；
- 层次化场景图；
- 从局部时间窗口整合为全局视频场景图；
- 图结构可视化；
- 人物 / 物体 / 动作 / 关系事件查询；
- 最终可交互 Demo。

## 1.2 当前阶段不要做的事情

当前不要优先做：

- 不要重新训练 HSGG；
- 不要先重跑全部 3 万多帧；
- 不要一开始复现 STTran / TEMPURA 的完整训练流程；
- 不要一开始上复杂端到端 Video-SGG 网络；
- 不要把全部 FrameGraph 直接粗暴拼成一个巨型图；
- 不要把帧内的 `person1/chair1/...` 当成全局 ID；
- 不要依赖 aggregate JSON 作为唯一真值；
- 不要为了追踪问题修改 HSGG 主流程。

当前优先级是：

> **先打通视频时间层。**

---

# 2. HSGG 在本项目中的定位

HSGG 负责的是“空间/单帧层次”：

```text
Image
  ↓
Hierarchical Entity Perception
  ↓
Geometry-Guided Relation Reasoning
  ↓
Frame Hierarchical Scene Graph
```

已有 HSGG 的主要能力：

- 单帧目标/实体；
- bounding box；
- 类别；
- 属性；
- part-whole 层次；
- 帧内关系；
- 层次化 HSG。

HSGG 原论文仍然以单张图像 `I` 作为输入，最终生成该图像的层次场景图。论文未来工作明确提到将层次化范式扩展到视频场景图和复杂时空关系。

因此本项目新增的核心应该是：

```text
HSGG: Spatial Hierarchy
        +
本项目: Temporal Hierarchy
```

最终形成两种层次：

### 空间层次

```text
person
├── shirt
├── hand
└── shoes
```

### 时间层次

```text
Video
├── Clip 1
│   ├── Frame 1
│   ├── Frame 2
│   └── Frame 3
├── Clip 2
└── Clip 3
```

---

# 3. 当前已有数据状态

已检查 `HSGG_OPENEQA_JSON.rar`。

压缩包内部目前主要包含两组 HSGG 推理结果：

- HM3D
- ScanNet

## 3.1 已验证统计

### HM3D

- 场景 manifest：64
- 输入采样帧：5145
- 成功生成 Frame HSG：4956
- 无场景图跳过：189
- 错误：0

### ScanNet

- 场景 manifest：93
- 输入采样帧：26597
- 成功生成 Frame HSG：26078
- 无场景图跳过：519
- 错误：0

### 合计

- 采样帧：31742
- 有效 Frame HSG：31034

这已经足够用于开发跨帧层次，不需要先继续扩数据量。

---

# 4. 当前 HSG JSON 的真实结构

单帧 JSON 顶层结构：

```json
{
  "image_path": "...",
  "objects": {},
  "hierarchy": {},
  "attributes": {},
  "relations": []
}
```

## 4.1 objects

当前 `objects` 中已经包含：

```text
image_path
boxes
labels
scores
stage2_empty
stage3_skipped
record_list
record_dict
```

例如：

```json
{
  "boxes": [
    [510.632, 220.739, 1126.917, 731.662]
  ],
  "labels": [
    "backsplash"
  ],
  "scores": [
    0.663
  ]
}
```

### 注意

`boxes[i] / labels[i] / scores[i]` 是同一个实体。

因此首先需要建立统一 observation：

```json
{
  "frame_id": 0,
  "local_index": 0,
  "local_name": "backsplash1",
  "label": "backsplash",
  "bbox": [510.632, 220.739, 1126.917, 731.662],
  "score": 0.663
}
```

---

# 5. hierarchy

当前数据真实字段：

```json
{
  "layer1_nodes": [],
  "layer2_mapping": {},
  "layer3_mapping": {}
}
```

例如：

```text
window1
├── handle2
│   └── knob2
├── handle3
│   └── knob1
└── door
```

这部分后续可以用来：

- 给实体增加 parent / child 信息；
- 区分主体实体和局部部件；
- 在跨帧匹配中增加 hierarchy context；
- 后续生成层次化 TrackGraph。

---

# 6. attributes

属性当前以 object index 为 key：

```json
{
  "7": "White wooden cabinet with glass doors",
  "5": "White porcelain sink with water in it"
}
```

注意：

- attributes 的 key 是 object index；
- 不是 `cabinet` / `cabinet1`；
- Adapter 阶段必须把它重新绑定到实体 observation。

标准化后：

```json
{
  "local_index": 7,
  "label": "cabinet",
  "attribute_text": "White wooden cabinet with glass doors"
}
```

---

# 7. relations

当前关系中包含：

```text
idx
subject_label
object_label
predicate
raw_output
selected_from_candidates
all_candidates
hsgg_source
```

例如：

```json
{
  "idx": [4, 10],
  "subject_label": "window1",
  "object_label": "handle2",
  "predicate": "has",
  "hsgg_source": "llava_inferred"
}
```

其中 `idx=[4,10]` 非常重要：

```text
4  -> objects[4]
10 -> objects[10]
```

后续跨帧追踪完成以后，应把帧内 relation：

```text
window1 --has--> handle2
```

转换为：

```text
track_001 --has--> track_007
```

---

# 8. 当前运行配置中已经出现过“视频增量”的痕迹

`run_manifest.json` 中已经存在这些参数：

```text
incremental_keyframe_interval
incremental_relation_ttl
incremental_match_iou
incremental_center_threshold
incremental_size_ratio_threshold
incremental_reuse_predicates
incremental_candidate_cache
incremental_verify_inherited
incremental_attribute_reuse
```

但当前数据实际运行配置：

```text
incremental_video = false
```

而且所有已检查 manifest 都没有开启 incremental video。

因此：

> 当前已有结果仍然是独立 Frame HSG，不是已经完成的 Video HSG。

这些参数可以作为我们自己设计跨帧算法时的参考，但不需要因此重跑 HSGG。

---

# 9. 当前最关键的数据约束

## 9.1 local ID 不是 global ID

如下两帧：

```text
Frame 100:
person1

Frame 102:
person1
```

不能因此认为是同一个人。

帧内后缀只是这一帧自己的编号。

我们必须创建：

```text
global track_id
```

例如：

```text
track_0001
├── frame100/person1
├── frame102/person2
├── frame104/man1
└── frame106/person1
```

---

## 9.2 `frame_scene_graphs/*.json` 作为 Source of Truth

当前实现中存在：

```text
objects.json
attributes.json
relations.json
hierarchy_mapping.json
scene_graphs.json
```

等聚合文件。

开发新模块时不要强依赖这些聚合文件。

第一版统一使用：

```text
<scene>/frame_scene_graphs/*.json
```

作为每帧 HSG 的主数据源，再由我们的代码自己构建：

```text
frames.json
tracks.json
clips.json
events.json
video_graph.json
```

---

## 9.3 原始 RGB 不在当前 RAR 中

JSON 中的 `image_path` 是服务器路径，例如：

```text
/cloud/data/openeqa/frames_stride2_offset0/...
```

RAR 本身没有包含这些 PNG。

因此 Demo 如果要显示：

```text
视频 / 图片 + bbox + Graph
```

需要另外提供：

- 原视频；
- 或 RGB 帧目录；
- 或建立 `asset_path_mapper`。

建议不要把绝对路径写死。

---

# 10. 总体工程架构

建议最终架构：

```text
┌─────────────────────┐
│ Existing HSGG JSON  │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│ FrameGraph Adapter  │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│ Entity Normalizer   │
│ Relation Normalizer │
└──────────┬──────────┘
           ↓
┌─────────────────────────────┐
│ Cross-frame Association     │
│ ByteTrack / OC-SORT 思想    │
│ + HSG semantic context      │
└──────────┬──────────────────┘
           ↓
┌─────────────────────┐
│ TrackGraph          │
└──────────┬──────────┘
           ↓
┌─────────────────────────────┐
│ Temporal Relation Smoothing │
│ TEMPURA 思想                │
└──────────┬──────────────────┘
           ↓
┌─────────────────────┐
│ ClipGraph           │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│ VideoGraph          │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│ Event Extraction    │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│ Search / Query      │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│ Gradio / Streamlit  │
└─────────────────────┘
```

---

# 11. 论文方法在本项目中的使用方式

## 11.1 HSGG

论文：

**HSGG: Training-Free Hierarchical Scene Graph Generation with Geometry-Guided Relation Reasoning**

在本项目中使用：

- FrameGraph；
- 层次实体；
- attribute；
- relation；
- 单帧空间结构。

不要把它当作跨帧 tracker。

---

## 11.2 ByteTrack

论文：

**ByteTrack: Multi-Object Tracking by Associating Every Detection Box**

官方实现：

`https://github.com/ifzhang/ByteTrack`

借鉴：

```text
高置信 detection 第一阶段匹配
            ↓
未匹配 Track
            ↓
低置信 detection 第二阶段匹配
```

本项目不是必须直接运行完整 ByteTrack。

第一版可以借它的：

- two-stage association；
- track lifecycle；
- detection confidence 处理思想。

---

## 11.3 OC-SORT

论文：

**Observation-Centric SORT: Rethinking SORT for Robust Multi-Object Tracking**

官方实现：

`https://github.com/noahcao/OC_SORT`

借鉴：

- observation-centric；
- 遮挡/非线性运动后的轨迹恢复；
- motion consistency；
- track state 管理。

对当前稀疏采样帧比“单纯依赖 Kalman 连续运动”更值得参考。

---

## 11.4 STTran

论文：

**Spatial-Temporal Transformer for Dynamic Scene Graph Generation**

官方实现：

`https://github.com/yrcong/STTran`

核心：

```text
Spatial Encoder
      ↓
Temporal Decoder
```

本项目不用复现其完整训练结构。

对应关系：

```text
STTran Spatial Encoder
          ↓
本项目已有 HSGG FrameGraph

STTran Temporal Decoder
          ↓
本项目 Temporal Graph Aggregator
```

主要借鉴：

> 单帧空间图必须经过时间建模后，才能成为 Dynamic Scene Graph。

---

## 11.5 TEMPURA

论文：

**Unbiased Scene Graph Generation in Videos**

方法：

**TEMPURA — TEmporal consistency and Memory Prototype guided UnceRtainty Attenuation**

官方实现：

`https://github.com/sayaknag/unbiasedSGG`

本项目重点借鉴：

> Temporal Consistency

例如：

```text
frame 10: person --holding--> cup
frame 12: person --holding--> cup
frame 14: person --near-----> cup
frame 16: person --holding--> cup
```

不要让单帧噪声马上改变全局关系。

经过时间聚合：

```text
person --holding--> cup
valid: frame10 ~ frame16
```

---

## 11.6 Action Genome

论文：

**Action Genome: Actions as Compositions of Spatio-Temporal Scene Graphs**

借鉴：

> Action / Event 可以视为时空对象关系随时间发生变化。

例如：

```text
t1: person near cup
t2: person touching cup
t3: person holding cup
```

可以进一步形成：

```text
Event:
person picks_up cup
```

第一版不必训练 Action Genome 模型。

可以先实现 rule-based event extraction。

---

## 11.7 VideoTree

论文：

**VideoTree: Adaptive Tree-based Video Representation for LLM Reasoning on Long Videos**

官方实现：

`https://github.com/Ziyang412/VideoTree`

借鉴：

> 长视频不应该被平铺成巨大序列，而应该使用 hierarchical / coarse-to-fine representation。

对应本项目：

```text
VideoGraph
  ↓
ClipGraph
  ↓
Track / Event
  ↓
FrameGraph
```

第一版不需要复现 VideoTree 的 query-adaptive tree construction。

先实现稳定的静态多层图结构。

---

# 12. 第一阶段数据模型

建议新建统一 schema。

---

## 12.1 FrameEntity

```python
class FrameEntity:
    frame_id: int

    local_index: int
    local_name: str

    label: str
    canonical_label: str

    bbox: list[float]       # x1,y1,x2,y2
    score: float

    attribute_text: str | None

    parent_local_name: str | None
    child_local_names: list[str]

    track_id: str | None
```

---

## 12.2 FrameRelation

```python
class FrameRelation:
    frame_id: int

    subject_local_index: int
    object_local_index: int

    subject_track_id: str | None
    object_track_id: str | None

    predicate_raw: str
    predicate_norm: str

    source: str
```

---

## 12.3 FrameGraph

```python
class FrameGraph:
    scene_id: str
    frame_id: int
    image_path: str

    entities: list[FrameEntity]
    relations: list[FrameRelation]
```

---

# 13. Track 数据结构

## 13.1 TrackObservation

```python
class TrackObservation:
    frame_id: int
    local_index: int
    local_name: str
    bbox: list[float]
    score: float
    label: str
    attribute_text: str | None
```

## 13.2 EntityTrack

```python
class EntityTrack:
    track_id: str

    canonical_label: str

    status: str
    # tentative / confirmed / lost / removed

    start_frame: int
    end_frame: int

    observations: list[TrackObservation]

    missed_count: int

    aggregated_attributes: list[str]

    parent_track_id: str | None
```

---

# 14. 跨帧匹配：V1 设计

这是当前最优先实现模块。

## 14.1 不要只用 IoU

纯 IoU：

```text
camera movement
object movement
sparse frames
occlusion
```

都会造成匹配失败。

使用：

\[
S_{match}
=
w_{iou}S_{iou}
+
w_cS_{center}
+
w_sS_{size}
+
w_lS_{label}
+
w_aS_{attr}
+
w_hS_{hierarchy}
+
w_rS_{relation}
\]

---

# 15. 各匹配项建议

## 15.1 IoU

```python
iou(track.last_bbox, entity.bbox)
```

归一化：

```text
0 ~ 1
```

---

## 15.2 Center similarity

bbox 中心：

```python
cx = (x1 + x2) / 2
cy = (y1 + y2) / 2
```

距离按图像对角线归一化：

\[
d =
\frac{\sqrt{(cx_i-cx_j)^2+(cy_i-cy_j)^2}}
{\sqrt{W^2+H^2}}
\]

转换为 similarity：

\[
S_{center} = e^{-d/\sigma}
\]

---

## 15.3 Size similarity

使用 bbox 面积：

\[
r = \frac{\min(A_i,A_j)}{\max(A_i,A_j)}
\]

直接：

```text
S_size = r
```

---

## 15.4 Label similarity

V1：

```text
相同 canonical_label -> 1
明显不同 -> 0
```

例如 normalize：

```text
man/person/woman -> person
sofa/couch -> couch
television/tv -> tv
```

V2 可以使用 embedding cosine similarity。

---

## 15.5 Attribute similarity

先不要直接上大模型。

V1：

- lower case；
- tokenize；
- 去停用词；
- Jaccard；
- 或简单 TF-IDF cosine。

例如：

```text
"white wooden cabinet with glass doors"
"white cabinet with glass door"
```

应该具有较高分。

---

## 15.6 Hierarchy similarity

比较：

```text
parent label
child label set
```

例如：

```text
handle
parent = window
```

比单纯：

```text
handle
```

稳定得多。

可定义：

```text
same parent canonical label: +score
child set similarity: +score
```

---

## 15.7 Relation context similarity

这是本项目最值得保留的方法点。

Track A 上一帧：

```text
chair
near table
below window
```

当前候选 C：

```text
chair
beside table
below window
```

即使 IoU 不高，scene context 仍然相似。

可以建立实体邻域签名：

```python
{
    ("near", "table"),
    ("below", "window")
}
```

再进行 Jaccard / semantic matching。

第一版 relation context 权重不要太高，因为单帧 relation 本身会抖动。

---

# 16. 初始权重建议

第一版：

```yaml
tracking:
  weight_iou: 0.30
  weight_center: 0.20
  weight_size: 0.10
  weight_label: 0.20
  weight_attribute: 0.10
  weight_hierarchy: 0.05
  weight_relation: 0.05
```

先能运行，再调参。

不要一开始寻找“理论最优权重”。

---

# 17. Candidate Gating

为了避免所有实体两两计算：

先做 hard gate。

候选必须满足至少一项：

```text
canonical_label 相同
或
label semantic similarity 很高
```

同时满足几何宽松约束：

```text
center distance < threshold
或
IoU > minimum_iou
```

对于静态环境 + 相机移动较大的场景：

center threshold 要比 MOT 行人场景更宽松。

---

# 18. Assignment

对：

```text
active_tracks × current_entities
```

生成 cost matrix：

```text
cost = 1 - match_score
```

然后：

```python
scipy.optimize.linear_sum_assignment
```

使用 Hungarian Assignment。

之后：

```text
matched
unmatched tracks
unmatched detections
```

分别处理。

---

# 19. Track 生命周期

状态：

```text
tentative
confirmed
lost
removed
```

建议：

```yaml
tracking:
  min_confirm_hits: 2
  max_missed_frames: 3
```

逻辑：

```text
new observation
  ↓
tentative

连续匹配 >= 2
  ↓
confirmed

若暂时未匹配
  ↓
lost

超过 max_missed
  ↓
removed
```

---

# 20. ByteTrack 式两阶段关联

建议直接用于 V1.5。

### Stage 1

高置信 observation：

```text
score >= high_score_threshold
```

先匹配。

### Stage 2

对 Stage 1 未匹配的 confirmed track：

再使用较低置信 observation。

原因：

HSGG detection 里一些真实实体 confidence 并不高。

---

# 21. TrackGraph

跨帧追踪完成后：

```text
FrameGraph local entity
          ↓
global track_id
```

例如：

```json
{
  "track_id": "track_00017",
  "canonical_label": "cabinet",
  "start_frame": 0,
  "end_frame": 42,
  "observations": [
    {
      "frame_id": 0,
      "local_index": 7
    },
    {
      "frame_id": 2,
      "local_index": 4
    }
  ]
}
```

注意：

```text
local_index
```

变化完全正常。

---

# 22. Relation Normalization

当前 predicate 是 open-vocabulary 文本。

需要进行归一化。

例如：

```text
beside
next to
adjacent to
close to
```

统一：

```text
NEAR
```

例如：

```text
on top of
on
resting on
```

视具体语义归一：

```text
ON
```

建议第一版建立人工 mapping：

```python
RELATION_ALIASES = {
    "beside": "near",
    "next to": "near",
    "adjacent to": "near",
    ...
}
```

不要第一版让 LLM 每条 relation 都在线归一化。

---

# 23. Temporal Relation

当 FrameRelation 的 subject/object 都被映射到 track 后：

```text
frame relation
↓
track relation observation
```

得到：

```text
track_001 --holding--> track_007 @ frame100
track_001 --holding--> track_007 @ frame102
track_001 --near-----> track_007 @ frame104
track_001 --holding--> track_007 @ frame106
```

---

# 24. TEMPURA 式 Temporal Consistency 简化版

不复现 TEMPURA 模型训练。

实现：

### 24.1 TTL

关系不会因为一帧缺失马上消失。

例如：

```yaml
temporal_relation:
  ttl_frames: 2
```

### 24.2 滑动窗口投票

窗口：

```text
最近 N 个 sampled frames
```

计算：

```text
holding = 4
near = 1
```

则：

```text
dominant_relation = holding
```

### 24.3 Confidence

可以：

\[
confidence =
\frac{\text{dominant predicate count}}
{\text{all observed predicates}}
\]

---

# 25. TemporalRelation 数据结构

```python
class TemporalRelation:
    subject_track_id: str
    object_track_id: str

    predicate: str

    start_frame: int
    end_frame: int

    confidence: float

    evidence_frames: list[int]
```

---

# 26. ClipGraph

第一版不要做复杂语义切镜。

因为 OpenEQA 当前只有帧序关系，当前 RAR 没有可靠真实视频 timestamp。

因此第一版：

```text
fixed window
```

例如：

```yaml
clip:
  sampled_frames_per_clip: 10
  overlap: 2
```

形成：

```text
Clip 0:
frame 0 ~ 18

Clip 1:
frame 16 ~ 34
...
```

如果之后获得原视频 FPS：

```text
frame_id -> timestamp
```

再切换成秒级窗口。

---

# 27. ClipGraph 应包含什么

```python
class ClipGraph:
    clip_id: str

    start_frame: int
    end_frame: int

    track_ids: list[str]

    relations: list[TemporalRelation]

    events: list[str]

    summary: str | None
```

图节点不是每一个 observation。

而是：

```text
Track Entity
```

因此能大幅压缩信息。

---

# 28. VideoGraph

VideoGraph 是 ClipGraph 的更高层聚合。

建议：

```python
class VideoGraph:
    scene_id: str

    tracks: dict[str, EntityTrack]

    clips: list[ClipGraph]

    temporal_relations: list[TemporalRelation]

    events: list[Event]
```

不要把每帧所有 bbox 都展开在 VideoGraph 可视化中。

需要 detail 时再 drill down。

---

# 29. Event

Event 统一数据结构：

```python
class Event:
    event_id: str

    subject_track_id: str | None
    action: str
    object_track_id: str | None

    start_frame: int
    end_frame: int

    confidence: float

    evidence_frames: list[int]

    source: str
```

---

# 30. Event V1：规则生成

第一版可以从 relation transition 提取。

例如：

```text
NEAR
  ↓
TOUCHING
  ↓
HOLDING
```

可映射为：

```text
pick_up
```

类似：

```text
standing_near chair
↓
sitting_on chair
```

可映射为：

```text
sit_down
```

第一版 Event 不要求非常强。

重点是让：

```text
人物 + 动作 + 物体 + 时间范围
```

这条链路能运行。

---

# 31. Event V2：VLM / LLM 总结

ClipGraph 已经把信息压缩后，再给 LLM：

```text
track1 = person
track2 = cup

relations:
t1 near
t2 touching
t3 holding
```

要求输出：

```json
{
  "subject": "track1",
  "action": "pick up",
  "object": "track2"
}
```

注意：

> 不要把几十/几百原始帧直接交给 LLM。

先 ClipGraph 压缩。

---

# 32. 长视频层次化结构

最终层次：

```text
VideoGraph
│
├── ClipGraph 000
│   ├── Event
│   ├── Track
│   ├── TemporalRelation
│   └── FrameGraph
│
├── ClipGraph 001
│
└── ClipGraph 002
```

与此同时，每一个 FrameGraph 内部还有 HSGG：

```text
Object
├── Part
└── Subpart
```

所以最终是：

```text
Temporal Hierarchy
        ×
Spatial Hierarchy
```

这是报告里非常重要的表达。

---

# 33. Query

至少支持：

```text
entity query
relation query
event query
```

例如：

```text
cabinet
person
holding
near
pick up
```

查询结果：

```json
{
  "query": "holding",
  "results": [
    {
      "start_frame": 100,
      "end_frame": 116,
      "subject": "track_01",
      "predicate": "holding",
      "object": "track_07"
    }
  ]
}
```

---

# 34. 第一版检索不要上向量数据库

直接构建：

```text
entity_index
relation_index
event_index
```

例如：

```python
relation_index["holding"] = [...]
entity_index["person"] = [...]
event_index["pick_up"] = [...]
```

Demo 足够快。

后面如果加入自然语言问题：

再增加 embedding / LLM。

---

# 35. 建议工程目录

```text
project/
│
├── configs/
│   └── default.yaml
│
├── data/
│   ├── hsgg_json/
│   ├── rgb/
│   └── processed/
│
├── src/
│   │
│   ├── schemas/
│   │   ├── frame.py
│   │   ├── track.py
│   │   ├── clip.py
│   │   ├── event.py
│   │   └── video.py
│   │
│   ├── io/
│   │   ├── hsgg_reader.py
│   │   ├── scene_loader.py
│   │   └── asset_resolver.py
│   │
│   ├── normalize/
│   │   ├── entity_normalizer.py
│   │   └── relation_normalizer.py
│   │
│   ├── tracking/
│   │   ├── matcher.py
│   │   ├── track_manager.py
│   │   ├── geometry.py
│   │   ├── semantic.py
│   │   └── context.py
│   │
│   ├── temporal/
│   │   ├── relation_aggregator.py
│   │   ├── clip_builder.py
│   │   └── event_extractor.py
│   │
│   ├── graph/
│   │   ├── track_graph.py
│   │   ├── clip_graph.py
│   │   └── video_graph.py
│   │
│   ├── query/
│   │   ├── index.py
│   │   └── search.py
│   │
│   └── visualization/
│       ├── frame_overlay.py
│       └── graph_renderer.py
│
├── app/
│   └── gradio_app.py
│
├── scripts/
│   ├── build_tracks.py
│   ├── build_clips.py
│   ├── build_video_graph.py
│   └── run_demo.py
│
└── tests/
```

---

# 36. 建议配置文件

```yaml
tracking:
  high_score_threshold: 0.5
  low_score_threshold: 0.2

  match_threshold: 0.55

  weight_iou: 0.30
  weight_center: 0.20
  weight_size: 0.10
  weight_label: 0.20
  weight_attribute: 0.10
  weight_hierarchy: 0.05
  weight_relation: 0.05

  min_confirm_hits: 2
  max_missed_frames: 3

temporal_relation:
  window_size: 5
  ttl_frames: 2
  dominant_ratio: 0.6

clip:
  sampled_frames_per_clip: 10
  overlap: 2
```

---

# 37. FrameGraph Adapter 的完成标准

输入：

```text
frame_scene_graphs/00000-rgb.json
```

输出：

```python
FrameGraph(...)
```

要求：

- box 与 label 正确对应；
- score 正确；
- attribute index 正确绑定；
- local_name 可以从 relation/hierarchy 对齐；
- parent-child 建立；
- relation 的 idx 正确引用实体；
- 不因为某一实体缺 attribute 而报错；
- 不因为没有 relation 而报错。

---

# 38. CrossFrameTracker V1 伪代码

```python
tracks = []

for frame in ordered_frames:

    entities = frame.entities

    active_tracks = get_active_tracks(tracks)

    score_matrix = build_match_matrix(
        active_tracks,
        entities
    )

    matches, unmatched_tracks, unmatched_entities = hungarian_match(
        score_matrix
    )

    for track_idx, entity_idx in matches:
        update_track(
            active_tracks[track_idx],
            entities[entity_idx]
        )

    for track in unmatched_tracks:
        mark_missed(track)

    for entity in unmatched_entities:
        create_new_track(entity)

    remove_expired_tracks()
```

---

# 39. Match Matrix 伪代码

```python
def compute_match_score(track, entity, frame):

    if not label_gate(track, entity):
        return 0.0

    s_iou = bbox_iou(track.last_bbox, entity.bbox)

    s_center = center_similarity(
        track.last_bbox,
        entity.bbox,
        frame.width,
        frame.height
    )

    s_size = size_similarity(
        track.last_bbox,
        entity.bbox
    )

    s_label = label_similarity(
        track.canonical_label,
        entity.canonical_label
    )

    s_attr = attribute_similarity(
        track.aggregated_attributes,
        entity.attribute_text
    )

    s_hier = hierarchy_similarity(
        track,
        entity,
        frame
    )

    s_rel = relation_context_similarity(
        track,
        entity,
        frame
    )

    return (
        W_IOU * s_iou
        + W_CENTER * s_center
        + W_SIZE * s_size
        + W_LABEL * s_label
        + W_ATTR * s_attr
        + W_HIER * s_hier
        + W_REL * s_rel
    )
```

---

# 40. 最小 Demo 页面

建议 Gradio：

```text
┌──────────────────────────────────────────────┐
│ Scene / Video Selector                       │
├──────────────────────┬───────────────────────┤
│ RGB / Video          │ Current Frame HSG     │
│ + Bounding Boxes     │                       │
├──────────────────────┼───────────────────────┤
│ Track Timeline       │ Current ClipGraph     │
├──────────────────────┴───────────────────────┤
│ VideoGraph                                    │
├──────────────────────────────────────────────┤
│ Query: [ person / object / relation / event ]│
├──────────────────────────────────────────────┤
│ Results                                       │
│ frame100~116  person holding cup              │
└──────────────────────────────────────────────┘
```

---

# 41. Demo 第一版推荐使用预处理结果

HSGG 单帧推理成本较高。

所以答辩 Demo 第一版：

```text
预处理 HSGG
+
现场运行 Track/Clip/VideoGraph/Query
```

而不是：

```text
现场上传长视频
↓
从头跑全部 HSGG
```

可以提供“上传视频”入口，但处理状态可以异步/预生成，不把实时 HSGG 作为第一版硬要求。

---

# 42. 实现顺序

## Milestone 1 —— JSON Adapter

目标：

```text
Raw HSG JSON
↓
FrameGraph
```

完成后保存：

```text
processed/frames.json
```

---

## Milestone 2 —— Cross-frame Tracking

目标：

```text
Frame entity
↓
track_id
```

输出：

```text
processed/tracks.json
```

必须能看出：

```text
不同帧的局部实体
↓
同一 global track
```

---

## Milestone 3 —— Temporal Relation

把：

```text
FrameRelation
```

转换为：

```text
TemporalRelation
```

输出：

```text
processed/temporal_relations.json
```

---

## Milestone 4 —— ClipGraph

固定窗口构图。

输出：

```text
processed/clips.json
```

---

## Milestone 5 —— VideoGraph

整合：

```text
Track
Clip
Temporal Relation
Event
```

---

## Milestone 6 —— Query

建立：

```text
entity_index
relation_index
event_index
```

---

## Milestone 7 —— Demo UI

显示：

```text
视频/图片
bbox
frame graph
clip graph
video graph
query result
```

---

# 43. 第一版 Definition of Done

达到以下条件就认为核心 Demo 已经打通：

- [ ] 能读取任一场景的所有 `frame_scene_graphs/*.json`
- [ ] 能按 frame_id 正确排序
- [ ] 每一个实体有标准化 FrameEntity
- [ ] 至少一部分跨帧重复实体能被赋相同 track_id
- [ ] Track 有 start/end 和 observations
- [ ] FrameRelation 能转换成 track-level relation
- [ ] Relation 有 temporal smoothing
- [ ] 能生成 ClipGraph
- [ ] 能生成 VideoGraph
- [ ] 能按 entity 查
- [ ] 能按 relation 查
- [ ] 能返回 evidence frame
- [ ] Demo 可显示图结构
- [ ] 点击查询结果可跳到对应帧

做到这里已经是“层次化视频场景图 Demo”。

---

# 44. V2 增强项

第一版完成后再做。

## 44.1 Appearance Embedding

如果有 RGB：

```text
bbox crop
↓
DINO / CLIP / ReID
↓
appearance embedding
```

加入：

\[
S_{appearance}
\]

适用于：

- 多个同类别物体；
- 人物交叉；
- 大幅相机运动；
- 遮挡后重新出现。

---

## 44.2 Deep OC-SORT / BoT-SORT 思想

仅在 V1 ID Switch 明显时再加。

---

## 44.3 Semantic Embedding

把：

```text
label
attribute
relation neighborhood
```

编码成 embedding。

解决：

```text
sofa ↔ couch
man ↔ person
television ↔ tv
```

---

## 44.4 自适应 Clip

固定窗口升级为：

```text
scene change
event change
graph similarity change
```

触发新的 Clip。

---

## 44.5 VideoTree 风格 Query-Adaptive Expansion

只有在基本 VideoGraph 已完成后再考虑。

---

# 45. 可以作为项目“小创新”的方法

普通 MOT 主要使用：

```text
motion
appearance
```

本项目可以明确提出：

> Hierarchical Scene Graph Guided Cross-Frame Association

即：

\[
S_{track}
=
S_{geometry}
+
S_{semantic}
+
S_{attribute}
+
S_{hierarchy}
+
S_{relation-context}
\]

意义：

HSGG 不只是拿来生成 bbox。

它提供的：

```text
attribute
part-whole hierarchy
relation neighborhood
```

可以反过来帮助视频实体关联。

这是当前最自然、最容易实现、最贴合项目主题的方法扩展。

---

# 46. 可做的小实验

后面如果要写报告/论文性质实验：

### Baseline A

```text
IoU only
```

### Baseline B

```text
IoU + center + size
```

### Baseline C

```text
geometry + label
```

### Ours

```text
geometry
+ label
+ attribute
+ hierarchy
+ relation context
```

比较：

- track continuity；
- ID switch；
- fragmented tracks；
- relation temporal consistency；
- Event query correctness。

即使没有完整 GT，也可以挑 5~10 个场景人工标注小规模验证集。

---

# 47. OpenEQA 当前特别需要注意

OpenEQA 当前结果更适合展示：

```text
跨帧环境记忆
静态物体持续存在
空间关系
全局环境图
```

如果后续需要重点展示：

```text
人物动作
事件变化
动作问答
```

可以再引入 NExT-QA / Action Genome 等真实视频数据。

但现在不要为了换数据集阻塞 TrackGraph 开发。

---

# 48. 代码开发原则

1. 所有新模块只读取 HSGG 结果，不修改 HSGG 原始 JSON。
2. `frame_scene_graphs` 是输入层。
3. 新结果保存到单独的 `processed` 目录。
4. 所有阈值进入 YAML，不硬编码。
5. 每个 matching component 都能单独关闭，方便消融实验。
6. 每一个 track match 最好保存 component scores，方便调试。
7. 不要 silent fallback。
8. 对 malformed JSON / 缺少字段给清晰错误。
9. 图构建层与 UI 解耦。
10. 核心算法必须可以命令行运行，不依赖 Gradio。

---

# 49. 调试时建议保存 match_debug

```json
{
  "frame_id": 102,
  "track_id": "track_001",
  "entity_index": 7,

  "scores": {
    "iou": 0.61,
    "center": 0.88,
    "size": 0.95,
    "label": 1.0,
    "attribute": 0.72,
    "hierarchy": 0.5,
    "relation": 0.4
  },

  "total": 0.76,
  "accepted": true
}
```

这个对分析 ID Switch 很重要。

---

# 50. 最终项目逻辑

最终不应该描述成：

> 对视频每帧跑一次 HSGG。

而应该描述成：

> 首先利用 HSGG 获得帧级层次化场景表示；随后通过结合几何、实体语义、属性、层次关系及图邻域上下文的跨帧实体关联，建立稳定的实体轨迹；在此基础上对关系进行时间一致性聚合，形成 TrackGraph 与 ClipGraph；最后将局部时间窗口逐层整合成全局 VideoGraph，并支持基于实体、关系和事件的长视频查询。

这句话可以作为整个项目的核心方法描述。

---

# 51. 下一步直接开发任务

当前第一个实际编码任务：

```text
实现 hsgg_reader.py
```

输入：

```text
scene/frame_scene_graphs/*.json
```

输出：

```python
list[FrameGraph]
```

第二个任务：

```text
实现 matcher.py + track_manager.py
```

先只开启：

```text
IoU
center
size
label
```

跑通。

第三个任务再增加：

```text
attribute
hierarchy
relation context
```

不要一次把所有功能写完再测试。

---

# 52. 给 AI 编程助手的短上下文

如果需要把项目交给另一个 Coding Agent，可以直接给它下面这段：

```text
本项目正在将已有的单帧 HSGG 输出扩展为层次化视频场景图。

不要重新运行或修改 HSGG。现有输入为每个场景的
frame_scene_graphs/*.json。

每个 JSON 含：
- objects: boxes / labels / scores
- hierarchy: layer1_nodes / layer2_mapping / layer3_mapping
- attributes: object-index -> attribute text
- relations: idx(subject/object index), subject_label, object_label, predicate

当前目标按顺序完成：
1. Raw HSG JSON -> normalized FrameGraph
2. 跨帧实体关联，生成稳定 global track_id
3. TrackGraph
4. relation normalization + temporal smoothing
5. fixed-window ClipGraph
6. VideoGraph
7. entity/relation/event query
8. Gradio Demo

跨帧匹配 V1 使用：
IoU + center distance + bbox size + canonical label，
Hungarian assignment + track lifecycle。

V2 再加入：
attribute similarity + hierarchy context + relation-neighborhood context。

所有算法参数放到 YAML。
frame_scene_graphs 是 source of truth。
不要把帧内 person1/chair1 后缀视为 global ID。
不要把 UI 与核心图构建算法耦合。
```

---

# 53. 参考论文

### 单帧层次场景图
- HSGG: Training-Free Hierarchical Scene Graph Generation with Geometry-Guided Relation Reasoning

### 跨帧实体
- ByteTrack: Multi-Object Tracking by Associating Every Detection Box
- Observation-Centric SORT: Rethinking SORT for Robust Multi-Object Tracking

### Dynamic Scene Graph
- Spatial-Temporal Transformer for Dynamic Scene Graph Generation (STTran)
- Unbiased Scene Graph Generation in Videos (TEMPURA)

### Event / Action
- Action Genome: Actions as Compositions of Spatio-Temporal Scene Graphs

### 长视频层次结构
- VideoTree: Adaptive Tree-based Video Representation for LLM Reasoning on Long Videos

---

# 54. 当前总判断

现阶段：

```text
Frame-level HSG
```

已经足够作为底座。

后面的主要开发量集中在：

```text
Temporal Integration
```

也就是：

```text
FrameGraph
    ↓
TrackGraph
    ↓
Temporal Relation
    ↓
ClipGraph
    ↓
VideoGraph
    ↓
Event / Query
```

下一步不要继续停留在方案讨论。

直接从：

```text
hsgg_reader.py
```

和：

```text
CrossFrameTracker V1
```

开始实现。
