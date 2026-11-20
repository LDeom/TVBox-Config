# backup_live_playlists.py 说明

## 用途
从本仓库 TVBox 配置提取 `lives`，按 URL 去重，轮换 UA 下载并最多展开 5 层 URL 套壳，默认 5 路并发保存每个源的 M3U 列表；并发可通过 `LIVE_BACKUP_WORKERS` 调整，范围限制为 1–10。

## 输出
- `sources/collected/live_backups/`：每个源独立的 M3U，文件名由源名和稳定 URL 摘要组成。
- `sources/collected/live_backups/index.json`、`list.txt`：源索引。
- `output/reports/live_backup_report.json`：成功、失败和频道数报告。

## 更新规则
每日更新覆盖同一源的原路径，不生成日期副本或历史版本。下载失败时保留原有有效文件。仅保存频道列表，不下载视频分片，不代表设备端可播放。


## TVBox 逐源聚合
每日备份完成后同步更新 sources/collected/直播源聚合.json：
- 每个直播源保留独立 lives 条目。
- 有本地 M3U 备份时优先使用仓库内 raw URL。
- 失败时若旧 M3U 存在则继续使用旧备份；否则回退到原始在线 URL。
- 总聚合 M3U 仍保留为额外入口。
- 工作流会将聚合 JSON 与单源备份、索引一并提交。

所有输出覆盖固定文件名和路径，不创建日期副本，也不删除原始直播源配置。
