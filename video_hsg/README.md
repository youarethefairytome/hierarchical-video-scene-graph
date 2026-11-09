# 层次化视频场景图 Demo

面向长视频理解的层次化视频场景图。单帧空间层次用已经生成的 HSGG JSON，本目录只做时间层。

```text
Frame HSG
  -> 跨帧关联（track_id）
  -> 时间关系
  -> ClipGraph
  -> VideoGraph
  -> 实体 / 关系 / 事件查询
  -> Gradio
```

原始数据留在上一级目录，不搬进代码目录，也不改 HSGG 的 JSON。

## 目录

```text
video_hsg/
  configs/default.yaml          阈值和路径
  src/video_hsg/
    io/reader.py                读取 frame_scene_graphs
    normalize/labels.py         类别、谓词归一化
    tracking/                   几何匹配、匈牙利关联、轨迹生命周期
    temporal/build.py           时间平滑、事件、Clip
    query/search.py             查询
    graph/export_neo4j.py       Neo4j Cypher 和 CSV
    visualization/render.py     框、场景图、时间线
    pipeline.py                 串起整条流水线
    service.py                  Demo 只调用这里
  app/gradio_app.py
  scripts/build_scene.py
  scripts/run_demo.py
  tests/test_core.py
  processed/navqa_seq0/         构建结果
```

## 运行

```powershell
cd video_hsg
pip install -r requirements.txt
python scripts/build_scene.py
python app/gradio_app.py
```

浏览器打开 `http://127.0.0.1:7860`。

## 视频理解与演示

首页「视频理解与演示」管理视频、重要实体、实体事件和视频概括，保留原来的「当前帧」「全视频三层」「时间层次」「查询」等页面。

### 仅使用已有 HSGG 结果

页面启动和切换视频只读取已绑定的结果，不运行本地检测、姿态模型或后台生成任务。后续实际方法的接入位置是 `configs/demo_videos.yaml` 中的视频与结果绑定。

默认视频为 NExT-QA `2535384528`（VidOR 路径 `0052/2535384528.mp4`）的前 12 秒稳定视角段，内容为高尔夫挥杆。原片末尾会转镜头，因此保留完整源视频，并单独裁剪展示段；这一段有轻微手持晃动。视频来自 [NExT-GQA 社区镜像](https://huggingface.co/datasets/shuzhig/nextgqa)，数据集背景参见 [NExT-QA 官网](https://doc-doc.github.io/docs/nextqa.html)。

对应已有结果为上级目录 `HSGG_NEXTQA_JSON/hsgg_every30_outputs.tar.gz` 内的 `hsgg_every30_first_half_default_hsgg/49_2535384528`。包内 `extract.log` 记录原视频 378 帧、25 fps、每 30 帧采样；已核对下载视频的编号、尺寸 640×480、帧数和帧率。展示使用源帧 0–299，只读取已有 JSON 中 0、30、…、270 这 10 个采样帧，按原帧号取画面。轨迹、时间关系、事件和 Clip 由原有时间聚合流程得到，不重新生成单帧识别结果。

首次准备或恢复演示素材：

```powershell
python scripts/prepare_nextqa_demo.py
python app/gradio_app.py
```

准备脚本下载时校验源视频 SHA-256，解出指定场景，裁剪视频并聚合已有 JSON，同时更新视频绑定指纹。它只由上述命令手动运行。`processed/nextqa_2535384528/preparation.json` 保存来源、帧号映射和聚合配置。原始结果包及 JSON 内容不变。

顶部「当前展示视频（所有页面同步）」统一切换 NExT-QA 与已有 CODa 数据。上传视频后所有页面也一起切换；尚无对应 HSGG 结果的视频只提供预览，并明确提示接入结果。清单在 `configs/demo_videos.yaml`。此前非数据集的 OpenCV 样例、本地模型及其生成结果已移除。

页面采用左右双栏：左侧预览视频和事件证据，右侧阅读概括、实体与事件，数量概览随历史结果一起更新。API 设置和素材导入位于下方折叠区；调用记录与 JSON 下载放在「记录与导出」。

在「模型与分析设置」中填写 API Base URL（或完整 `/chat/completions` 地址）、支持 Function Calling 的文本模型 ID 和 Key。分析只发送文本图数据；视频和画面用于人工对照。可在启动前配置环境变量：

填写连接信息后点击「获取可用模型」，通过该地址的 `GET /models` 读取账号可见模型，随后在模型下拉框选择；也支持手动输入模型 ID。获取列表不调用模型、不创建分析记录；留空的 Key 使用 `VIDEO_LLM_API_KEY`。列表不保证所有模型支持工具调用，请选择支持 Function Calling 的文本模型。地址或 Key 改变后可重新获取；不提供模型列表的服务可直接手动填写。

模型列表和分析请求均使用应用标识 `VideoHSG/1.0`，避免部分网关拒绝 Python 默认客户端标识。列表请求失败时，设置区持续显示 HTTP 状态、脱敏后的服务端说明和实际请求地址，并区分鉴权、网关拦截、证书和超时问题。失败或修改连接设置不会清空当前模型和上次列表。

```powershell
$env:VIDEO_LLM_BASE_URL = "https://你的服务地址/v1"
$env:VIDEO_LLM_MODEL = "支持工具调用的文本模型ID"
$env:VIDEO_LLM_API_KEY = "你的Key"
python app/gradio_app.py
```

在网页填好 API 地址、Key 和模型后，点击「保存连接设置」，会保存为项目根目录 `video_hsg/.env` 中的 `VIDEO_LLM_BASE_URL`、`VIDEO_LLM_API_KEY`、`VIDEO_LLM_MODEL`，并更新当前服务进程的环境变量，立即生效。服务启动时自动读取这三个变量，项目 `.env` 中的保存值优先；刷新页面会重新读取当前配置。作用范围为当前项目服务。

保存成功后密码框清空，Key 仍保留在服务端；密码框留空时保存会保留旧 Key，填写新值后保存即可更换。`.env` 已加入 Git 忽略，主服务也禁止通过文件接口下载该文件。Key 不回填到浏览器，不写入分析数据库、模型请求档案或结果导出。未点击保存时，页面输入仅用于当前请求。未配置接口时仍可切换视频、导入结果和回放历史。

点击「开始分析 / 读取缓存」后，文本模型先获得当前视频的场景图概览，再通过 `search_graph` 搜索、`get_node` 查看节点及邻接关系、`get_frame` 读取采样帧的实体/关系/部件图、`graph_overview` 分页检查全段覆盖。工具只访问已绑定的当前视频场景图，不访问视频画面、外部网络或其他视频数据。缺少有效 HSGG 结果时，在调用模型前阻止分析。

默认最多 3 轮图检索，每轮最多执行 2 个查询，随后要求输出最终结果；最多发出 4 次模型请求。输出 token 上限默认填 `0`，表示请求中不发送 `max_tokens`，由服务商采用默认输出长度；应用不再设置 2432 或 8192 的限制。也可填写任意正整数作为显式上限，具体可用范围由服务商决定。服务商和模型自身仍可能因默认长度或上下文限制截断，不自动重试。检索阶段回传模型返回的 `reasoning_content`，最终阶段使用新的纯文本证据上下文，移除工具定义和工具调用消息，并设置 `response_format: {"type": "json_object"}`。兼容要求参见 [DeepSeek 多轮工具调用说明](https://api-docs.deepseek.com/guides/thinking_mode/)和 [JSON 输出说明](https://api-docs.deepseek.com/guides/json_mode/)。节点、关系和事件作为图证据输入，模型返回实体、事件、概括和不确定性；实体需附 `graph_node_ids`，事件需附 `graph_evidence`，引用未检索节点的结果不会作为成功分析保存。时间按图的源帧映射到视频秒数；本页点击事件仍可人工查看相应画面。预处理模型的错误、跟踪断裂和稀疏采样均需在概括中说明。

「图检索过程」展示本次模型的查询参数与返回证据；每次模型响应立即保存原文，后续查询失败也可回收之前的输出。成功结果自动保存在 `processed/video_analysis/archive.sqlite3`。同一视频内容、场景图指纹、接口、模型、提示词、检索轮数及输出上限优先命中缓存，不发送请求。默认不自动重试。「重新分析」会明确再次调用接口，并新增一条历史，旧记录保留。切换视频自动加载该视频最近结果，也可从历史列表回放，点击「恢复这次分析的调用参数」后复用原参数。重启不会清空历史。旧版画面分析记录保留并标记，仅用于回放，不会命中新版图检索缓存；图数据发生变化后也不会命中旧图的缓存。

接口已经返回但结果不符合 JSON 结构或被截断时，原始响应和图检索证据保存在 `processed/video_analysis/raw_outputs/`。完整 JSON 外带前言或代码块时可直接提取，但不会修补截断结果、执行原始 DSML 工具文本或跳过节点引用校验。若只有工具调用而没有概括，页面明确提示原因并保留当前展示。

再次点击普通「开始分析 / 读取缓存」，会寻找当前视频、图指纹、接口、模型、问题和检索轮数一致的未完成记录，重新核对已有图证据后，只发出一次最终 JSON 概括请求；提高 token 上限也可复用证据。此操作仍会产生一次模型调用。点击「重新分析」则从头运行，不复用失败记录。成功后归档并按正常缓存复用。已有完整结果 JSON 也可自行修正后导入。连接超时不能保证服务端未处理，请先检查服务端记录。

「记录与导出」可下载带视频指纹的 JSON；「导入已有分析结果」可恢复档案，视频指纹不匹配时会拒绝导入。也可导入以下裸结果对象（需自行确认与当前视频对应；导入记录单独标记来源，不冒充 API 缓存）：

```json
{
  "entities": [
    {"id": "E1", "name": "实体名称", "category": "人物", "description": "外观和重要性", "evidence_seconds": [0.0]}
  ],
  "events": [
    {"start_seconds": 0.0, "end_seconds": 1.0, "entity_ids": ["E1"], "description": "事件描述"}
  ],
  "summary": "这里填写已经得到的视频概括",
  "limitations": "这里填写不确定性"
}
```

`data/` 和 `processed/` 已被 Git 忽略；备份演示资料时请同时备份这两个目录。切换视频会停止播放、回到起点、清空查询和高亮，并更新大模型历史。无对应场景图时只显示真实视频预览，其他图、轨迹和比较数据保持为空，等待后续方法结果接入。三维图的视角与节点选择也随视频重置。

为视频接入已生成的 HSGG 结果，在 `configs/demo_videos.yaml` 的相应视频项填写 `scene_bundle`、`scene_video_sha256`、可选的 `scene_source_id`、`rgb_root` 和 `boxes_video`，然后重启。`scene_video_sha256` 必须为该视频文件的 SHA-256；也可将指纹写在 bundle 的 `meta.video_sha256` 中。已有 NExT-QA 和 CODa 条目均已完成绑定。`graph_frame_mapping: sampled_video` 表示视频每一帧对应 bundle 的一个采样帧，帧数必须一致；原始视频则用 `source_frame`，按 bundle 的源帧号读取。缺少指纹、指纹不符或帧号不匹配时拒绝展示该图，避免视频与结果混用。

NExT-QA 展示片段已绑定已有 HSGG 结果。大模型概括结果保留独立历史缓存，配置 API 和 Key 后手动调用；切换页面不会触发调用。

离线测试（使用本地模拟工具调用接口，不消耗模型额度）：

```powershell
python -m unittest discover -s tests -v
```

原视频来自 UT Austin CODa 数据集的序列 0、相机 cam0，只下载和 HSGG 对齐的采样帧：

```powershell
python scripts/download_rgb.py
python scripts/build_videos.py
```

页面上「播放」按采样帧连续播放。「在原视频上显示识别框」可以关掉框，只看原图。整段 mp4 在当前帧页的视频播放器里，勾选识别框会换成带框的那一段。

`python scripts/run_demo.py` 会在结果不存在时先构建再打开页面。

通用构建命令默认读取 CODa 的已有 JSON；网页默认展示 NExT-QA 稳定视角片段。换场景：

```powershell
python scripts/build_scene.py --scene D:\path\to\scene --out processed\my_scene
```

## 图怎么看

页面里的 VideoGraph 是属性图：`Track`、`Clip`、`Event` 是节点，`SCENE_RELATION`、`PART_OF` 是关系。展示用 NetworkX，不需要安装 Neo4j。

若要放进 Neo4j Browser，打开 `processed/navqa_seq0/neo4j/browser.cypher` 整段执行。完整表是同目录的 CSV。
