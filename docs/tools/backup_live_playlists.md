# backup_live_playlists.py 说明

## 用途
从本仓库 TVBox 配置提取 `lives`，按 URL 去重，轮换 UA 下载并最多展开 5 层 URL 套壳，保存每个源的 M3U 列表。

## 输出
- `sources/collected/live_backups/`：每个源独立的 M3U，文件名由源名和稳定 URL 摘要组成。
- `sources/collected/live_backups/index.json`、`list.txt`：源索引。
- `output/reports/live_backup_report.json`：成功、失败和频道数报告。

## 更新规则
每日更新覆盖同一源的原路径，不生成日期副本或历史版本。下载失败时保留原有有效文件。仅保存频道列表，不下载视频分片，不代表设备端可播放。
