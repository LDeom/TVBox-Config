# 工具目录

## 自动源维护流程

主入口：`python3 tools/source_pipeline.py`

数据来源只限本仓库已经收录的 JSON 配置和直播文件；不会把其他仓库的配置文件同步覆盖进来。脚本只会请求本仓库配置中明确列出的点播 API 与直播列表 URL。

### 流程模块

1. 扫描 `sources/configs/vod/*.json`、`sources/vod/*.json` 和 `sources/live/`。
2. 提取 type 0/1 点播 API、直播列表 URL、Python 站点及在线配置包入口。
3. 保守规范化 URL 并去重；保留原始查询参数，不重排可能带签名的参数。
4. 并发请求点播 API；识别 JSON、JSONP、Base64、GZIP、2423-AES、XML 响应，要求出现影视列表和影视字段才保存。
5. 新响应通过结构检查后写入 `sources/collected/api/`；响应无效或请求失败时保留已有缓存，替换缓存前备份上一份有效数据。
6. 提取本地和远程声明的直播列表，生成 M3U/TXT 和聚合 JSON。
7. 生成采集站、Py 站、在线配置包索引及完整巡检报告。

### 生成文件

- `sources/collected/cjlist.txt`：去重采集站清单。
- `sources/collected/采集站聚合.json`、`海量采集聚合接口.json`：采集站聚合数据。
- `sources/collected/pylist.txt`、`Py站聚合.json`、`海量py聚合接口.json`：Python 站点清单和聚合数据。
- `sources/collected/tvbox-live.m3u`、`livelist.txt`、`live.json`、`直播源聚合.json`：直播列表及 TVBox 兼容入口。
- `sources/collected/api/`、`api_index.json`：API 有效响应缓存及索引。
- `sources/collected/在线配置包索引.json`：在线配置入口索引；本仓库内链接会映射到本地文件，外部配置入口只登记。
- `sources/collected/online_package_download_index.json`、`packages/`：仅处理 `rylinks.txt` 明确列出的在线包；不会自动抓取总配置中的外部配置入口。
- `output/history/api/`：API 缓存更新前最多保留 5 个有效版本。
- `output/history/packages/`：在线包更新前的历史版本。
- `output/reports/source_pipeline_report.json`：运行统计、失败原因和源状态。

### 本地运行

```bash
python -m pip install -r requirements.txt
python3 tools/maintain_local_json.py
python3 tools/source_pipeline.py --workers 5
```

只做本地解析、不访问外部地址：

```bash
python3 tools/source_pipeline.py --offline
```

### 状态边界

- HTTP 2xx 不代表返回影视数据。
- 影视 JSON/XML 结构有效不代表播放地址真实可播放。
- 直播列表能解析不代表每个直播流都能播放。
- 采集站和 Py 站只提取、索引，不执行远程 Python 代码。
- 本机、局域网及非公网地址会被拦截；失败源不会导致旧缓存被删除。
