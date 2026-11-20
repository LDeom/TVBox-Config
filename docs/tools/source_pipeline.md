# source_pipeline.py 说明

## 用途
仓库主采集管线：扫描本地 TVBox JSON，提取点播 API、直播列表、采集站、Py 站和在线配置入口；对明确登记的公网 URL 做有限采集和聚合。

## 主要输出
- `sources/collected/api/`、`api_index.json`：有效影视 API 快照及索引。
- `cjlist.txt`、`pylist.txt` 和对应聚合 JSON。
- `live/`、`tvbox-live.m3u`、`live.json`、直播聚合 JSON。
- 在线配置包索引、镜像推荐和 `output/reports/source_pipeline_report.json`。

## 更新规则
成功采集直接覆盖固定缓存路径；失败时保留旧缓存，不生成历史版本副本。只解析和提取站点信息，不执行远程 Python 代码。
