# source_pipeline.py 说明

## 用途
仓库主采集管线：扫描本地 TVBox JSON，提取点播 API、直播列表、采集站、Py 站和在线配置入口；对明确登记的公网 URL 做有限采集和聚合。

## 主要输出
- `sources/collected/api/`、`api_index.json`：有效影视 API 快照及索引。
- `cjlist.txt`、`pylist.txt` 和对应聚合 JSON。
- `live/`、`tvbox-live.m3u`、`live.json`、TVBox 兼容的逐源 `lives` 聚合 JSON。
- 在线配置包索引、镜像推荐和 `output/reports/source_pipeline_report.json`。

## 更新规则
成功采集直接覆盖固定缓存路径；失败时保留旧缓存，不生成历史版本副本。只解析和提取站点信息，不执行远程 Python 代码。


## TVBox 直播聚合入口
sources/collected/直播源聚合.json 不再只暴露一个总 M3U。它会为当前配置中每个直播列表保留独立 lives 条目：
- 已有有效单源备份时，url 指向仓库内 sources/collected/live_backups/ 对应 M3U。
- 单源下载失败但旧备份存在时，继续引用旧备份。
- 没有可用备份时，保留原始直播列表 URL。
- 另保留“TVBox-Config 本地聚合直播”总 M3U 入口。
- source_count、local_backup_count、online_fallback_count 和 channel_count 记录汇总数量。

主采集流程和每日单源直播备份流程都会重建该聚合 JSON，固定覆盖原路径。
