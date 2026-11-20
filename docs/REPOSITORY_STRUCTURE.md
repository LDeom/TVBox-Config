# TVBox-Config 仓库结构

- `sources/vod/`：点播配置文件和导入入口。
- `sources/configs/vod/`：本地化点播配置。
- `sources/live/`：原始直播 JSON/M3U/TXT。
- `sources/js/`：JavaScript 采集或解析脚本。
- `sources/jar/`：Java 依赖或插件包。
- `sources/collected/`：从本仓库配置提取的 API 缓存、采集站/Py 站聚合和直播列表。
- `tools/`：源检测、采集、整理和维护工具。
- `output/reports/`：JSON/CSV 检测和维护报告。
- `output/history/api/`：API 缓存替换前的上一份有效版本。

## 自动维护流程

GitHub Actions 每日执行：

1. 扫描本仓库 JSON，修复安全可确定的 BOM/尾随逗号问题。
2. 提取本仓库配置内的 type 0/1 点播 API、直播列表、Py 站和在线配置包引用。
3. 对 API 和直播列表 URL 去重、检查公网可达性并限速并发请求。
4. 检查 API 是否返回有效影视 JSON/XML；有效响应缓存到 `sources/collected/api/`。
5. 失败响应不覆盖旧缓存；缓存更新前备份上一份有效文件。
6. 生成采集站、Py 站、直播 M3U/TXT、TVBox 直播 JSON 及配置入口索引。
7. 写入 `output/reports/source_pipeline_report.json`。

## 主要生成入口

- `sources/collected/cjlist.txt`
- `sources/collected/海量采集聚合接口.json`
- `sources/collected/pylist.txt`
- `sources/collected/海量py聚合接口.json`
- `sources/collected/tvbox-live.m3u`
- `sources/collected/livelist.txt`
- `sources/collected/live.json`
- `sources/collected/直播源聚合.json`
- `sources/collected/在线配置包索引.json`
- `sources/collected/api_index.json`

## 可用性标准

1. 已收录：文件存在于仓库。
2. HTTP 可访问：请求成功，不代表返回影视数据。
3. 数据结构有效：返回 JSON/XML 且出现影视列表特征。
4. 直播列表可解析：仅表示列表格式可读，不代表频道流可播放。
5. 可播放：还需逐条验证播放地址，不能由 API 结构检测代替。

未经检测的文件不得标注为可用。原始源应保留；清理操作先备份再执行。远程 Python 插件只提取 URL，不执行代码。
