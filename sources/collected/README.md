# 自动采集结果

此目录由 `tools/source_pipeline.py` 根据本仓库已有配置生成。不要手工修改自动生成文件；如需调整逻辑，请修改工具脚本并运行 GitHub Actions。

| 文件/目录 | 内容 |
|---|---|
| `cjlist.txt` | 去重后的 type 0/1 点播 API 清单 |
| `海量采集聚合接口.json` | TVBox 采集站聚合 JSON |
| `pylist.txt` | Python 站点 URL 清单；只提取，不执行 |
| `海量py聚合接口.json` | Python 站点聚合 JSON |
| `tvbox-live.m3u` | 合并后的直播 M3U |
| `livelist.txt` | 合并后的直播 TXT |
| `live.json` | 按频道分组的直播 JSON |
| `直播源聚合.json` | 指向本仓库 M3U 的 TVBox lives 配置片段 |
| `在线配置包索引.json` | 本仓库总配置中在线配置入口及本地映射检查 |
| `api_index.json` | API 采集状态、镜像分组和缓存文件索引 |
| `api/` | 通过影视数据结构检查的 API 响应快照 |
| `live/` | 已解析的远程直播列表快照 |

API 响应只有在结构验证通过后才会保存。失败不会覆盖旧快照；替换前会将上一份有效文件备份到 `output/history/api/`。HTTP 成功、数据结构有效、实际可播放是不同等级。
