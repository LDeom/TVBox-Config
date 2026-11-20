# TVBox-Config 仓库结构

- `sources/vod/`：点播配置文件。
- `sources/live/`：直播源文件。
- `sources/js/`：JavaScript 采集或解析脚本。
- `sources/jar/`：Java 依赖或插件包。
- `sources/pending/`：尚未分类或待检查的源。
- `tools/`：本地检测、整理工具。
- `output/vod/`：点播检测后的整理结果。
- `output/live/`：直播检测后的整理结果。
- `output/reports/`：CSV/JSON 检测报告。

## 可用性标准

1. 已收录：文件存在于仓库。
2. HTTP 可访问：请求成功，不代表返回影视数据。
3. 数据结构有效：返回 JSON/XML 且出现影视列表特征。
4. 可播放：还需验证播放地址，不能由 API 结构检测代替。

未经检测的文件不得标注为可用。原始源应保留，清理操作先备份再执行。
