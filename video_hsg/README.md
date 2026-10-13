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

原视频来自 UT Austin CODa 数据集的序列 0、相机 cam0，只下载和 HSGG 对齐的采样帧：

```powershell
python scripts/download_rgb.py
python scripts/build_videos.py
```

页面上「播放」按采样帧连续播放。「在原视频上显示识别框」可以关掉框，只看原图。整段 mp4 在当前帧页的视频播放器里，勾选识别框会换成带框的那一段。

`python scripts/run_demo.py` 会在结果不存在时先构建再打开页面。

默认场景是 `HSGG_NAVQA_JSON/hsgg_navqa_seq0_every10_full`。换场景：

```powershell
python scripts/build_scene.py --scene D:\path\to\scene --out processed\my_scene
```

## 图怎么看

页面里的 VideoGraph 是属性图：`Track`、`Clip`、`Event` 是节点，`SCENE_RELATION`、`PART_OF` 是关系。展示用 NetworkX，不需要安装 Neo4j。

若要放进 Neo4j Browser，打开 `processed/navqa_seq0/neo4j/browser.cypher` 整段执行。完整表是同目录的 CSV。
