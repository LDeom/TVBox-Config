# 参考仓库后端能力移植记录

参考项目：<https://github.com/lubin776/tvbox-api-backup>

参考项目声明采用 GNU GPL-3.0。当前移植批次参考了公开的输入清单格式、工作流组织方式和功能行为，新增实现由本仓库独立编写，没有直接复制其 Python 下载器源代码。若后续确需复制或改编参考仓库代码，必须先评估并遵守 GPL-3.0 的版权声明、许可证和源码提供义务；本说明不构成法律意见。

## 已对接的能力

| 参考项目能力 | 本仓库实现 | 说明 |
| --- | --- | --- |
| `apilinks.txt` 专用 API 清单 | `apilinks.txt`、`tools/api_link_catalog.py` | 支持单地址、同名多镜像、逗号/竖线格式；只维护本仓库自己的清单 |
| API 批量下载与镜像检查 | `tools/source_pipeline.py`、`tools/refresh_api_catalog.py` | 复用本仓库安全 HTTP 层，识别有效影视 JSON/XML，按有效性和响应耗时推荐线路 |
| TVBox JSON 配置独立备份 | `tools/backup_tvbox_configs.py` | 只读取 `apilinks.txt`；按同名镜像顺序回退，保存原始 JSON 与相对资源地址绝对化副本，生成索引/清单/历史版本；不执行远程代码 |
| 镜像优选配置 | `sources/collected/api_mirror_config.json` | 生成独立的 TVBox `sites` 配置片段，不改写原始配置 |
| API 分页增量采集 | `tools/api_pagination.py` | 手动启用；识别标准分页元数据，最多 10 页（脚本上限 20）；全部成功才发布，失败保留旧文件 |
| 在线包下载 | `tools/refresh_online_packages.py` | 只处理 `rylinks.txt` 明确填写的 URL；只解析 JSON，不执行远程代码 |
| 直播源抽检 | `tools/live_stream_health.py` | 检查 HTTP、HLS 清单及首个媒体分片；不声称等同设备端播放 |
| 采集站/Py 站/直播聚合 | `tools/source_pipeline.py` | 已有实现继续复用，不重复导入参考仓库的数据文件 |

## 工作流

- `.github/workflows/maintain-local-json.yml`：每日综合维护；读取本仓库配置，处理 API、直播列表、在线包清单和本地化依赖。
- `.github/workflows/refresh-api-catalog.yml`：手动 API 巡检，可选分页采集。
- `.github/workflows/backup-tvbox-configs.yml`：每日/手动备份 `apilinks.txt` 中明确登记的 JSON 配置；空清单时只生成空报告，不会擅自导入参考仓库数据。
- `.github/workflows/refresh-online-packages.yml`：手动在线包刷新。
- `.github/workflows/check-live-health.yml`：手动直播健康抽检。

各写入工作流共用 `tvbox-repo-maintenance` 并发组，避免同时推送互相覆盖。

## 安全和边界

- 所有网络请求使用本仓库 `tools/fetch_util.py`，限制超时、响应大小、重定向并阻止非公网地址。
- 不从参考仓库同步 JSON、直播列表、API 清单或在线包链接。
- 不覆盖本仓库原始配置；失败结果保留历史有效缓存。
- TVBox 配置备份分别保存解码后的原始 JSON 和资源 URL 绝对化副本；绝对化副本不覆盖原件，且不下载或执行 spider/JAR/JS 文件。
- `apilinks.txt` 当前未填写的条目不会被自动猜测或从参考仓库复制；备份工作流只处理用户明确登记的 URL。
- 在线包没有真实输入链接时不会虚构下载结果。
- HLS 首分片可访问仍不代表播放器、DRM、解码或设备兼容性一定正常。
- API 分页只处理能识别出分页元数据的 JSON API；默认关闭，避免对未知接口盲目翻页。
