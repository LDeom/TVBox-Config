# 工具目录

## 自动源维护流程

主入口：`python3 tools/source_pipeline.py`

数据来源只限本仓库已经收录的 JSON 配置和直播文件；不会把其他仓库的配置文件同步覆盖进来。脚本只会请求本仓库配置中明确列出的点播 API 与直播列表 URL。API 清单优先读取 `apilinks.txt`；当其缺失或为空时，可回退读取旧版 `api_list.json` 的 `API_LIST`/`API_MIRRORS`。旧版 `api_list.py` 仅允许 `API_LIST`/`API_MIRRORS` 字面量赋值，经 AST 安全解析；不导入或执行任何 Python 代码。

### 流程模块

1. 扫描 `sources/configs/vod/*.json`、`sources/vod/*.json` 和 `sources/live/`。
2. 提取 type 0/1 点播 API、直播列表 URL、Python 站点及在线配置包入口。
3. 保守规范化 URL 并去重；保留原始查询参数，不重排可能带签名的参数。
4. 并发请求点播 API；识别 JSON、JSONP、Base64、GZIP、2423-AES、XML 响应，要求出现影视列表和影视字段才保存。
5. 新响应通过结构检查后写入 `sources/collected/api/`；响应无效或请求失败时保留已有缓存，成功时覆盖原路径，不生成历史副本。
6. 提取本地和远程声明的直播列表；对仅返回单个 URL 的套壳列表递归穿透，最多 5 层，检测循环引用，并继续使用统一公网 URL 校验、超时和响应大小限制。
7. 生成 M3U/TXT 和聚合 JSON；直播报告记录最终 URL、穿透链和层数。
8. 对同名 API 镜像按影视数据有效性和响应时间评分，生成首选线路与备用候选；只提供建议，不自动改写原始配置。
9. 生成采集站、Py 站、在线配置包索引及完整巡检报告。

### TVBox 配置本地化

执行 `python3 tools/localize_tvbox_configs.py`，为 `sources/configs/vod/*.json` 生成可导入的本地化副本，输出到 `sources/collected/configs/`。原始配置文件保持不变。

- 只处理本仓库登记的配置，不下载或覆盖外部完整配置。
- LDeom 自有 GitHub raw 依赖沿用仓库既有路径；第三方公开 HTTP(S) 文件依赖按主机和路径缓存到 `sources/dependencies/external/<host>/`。
- 支持 JS/JAR/PY/JSON/TXT/PNG/JPG/JPEG/GIF/WEBP/ZIP/APK/NODE；M3U/M3U8/XML 明确排除。
- 第三方缓存每日下载并校验后原子覆盖原路径；下载失败保留旧缓存。URL 查询参数变化不会产生日期副本或改变文件路径。
- JAR/ZIP/APK 检查归档结构、大小和 CRC；APK 还检查 AndroidManifest.xml；JSON 检查解析；文本检查 UTF-8；图片和 NODE 检查文件签名。
- 仅将成功下载或已有有效缓存的依赖 URL 改写到本仓库；失败和不支持的链接保留原样并写入报告。
- 原始配置不修改；下载的 JS/PY/JAR/NODE 不执行。
- 报告：`output/reports/config_localization_report.json`。

## ZIP 安全导入

手动运行 `python3 tools/import_config_zip.py --zip package.zip`，或使用 `--url` 指定公开 ZIP 直链。校验通过后仅解压到 `imports/staging/`，不会自动合并进正式配置。GitHub Actions 工作流 `.github/workflows/import-config-zip.yml` 仅手动触发。说明见 `docs/tools/import_config_zip.md`。

## 辅助资源差异比较

运行 `python3 tools/compare_auxiliary_resources.py`，只读取参考仓库 `cy/` 目录元数据，与本地资源索引进行类别覆盖比较，生成 `sources/collected/auxiliary_resource_comparison.json`。不会下载或导入参考 JSON 内容。说明见 `docs/tools/compare_auxiliary_resources.md`。

## 辅助资源索引

运行 `python3 tools/build_resource_catalog.py`，扫描本仓库已有依赖、JS、JAR、Python、直播及配置文件，固定覆盖生成 `sources/collected/resource_catalog.json`。不导入外部资源，也不执行插件代码。说明见 `docs/tools/build_resource_catalog.md`。

## 生成文件

- `sources/collected/cjlist.txt`：去重采集站清单。
- `sources/collected/采集站聚合.json`、`海量采集聚合接口.json`：采集站聚合数据。
- `sources/collected/pylist.txt`、`Py站聚合.json`、`海量py聚合接口.json`：Python 站点清单和聚合数据。
- `sources/collected/tvbox-live.m3u`、`livelist.txt`、`live.json`、`直播源聚合.json`：直播列表及 TVBox 兼容入口。
- `sources/collected/api/`、`api_index.json`：API 有效响应缓存及索引。
- `sources/collected/resource_catalog.json`：本地辅助资源清单。
- `sources/collected/mirror_recommendations.json`：镜像健康评分、首选线路和备用候选。
- `sources/collected/在线配置包索引.json`：在线配置入口索引；本仓库内链接会映射到本地文件，外部配置入口只登记。
- `sources/collected/online_package_download_index.json`、`packages/`：仅处理 `rylinks.txt` 明确列出的在线包；不会自动抓取总配置中的外部配置入口。
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
- 本机、局域网及非公网地址会被拦截；失败源不会导致旧缓存被删除；成功更新直接覆盖原文件路径，不生成历史副本。
- 共享 HTTP 客户端包含主机级熔断：连续 4 次网络/408/429/5xx 失败后冷却 60 秒，冷却后只允许一个半开探测；每个 URL 默认总请求预算 30 秒，覆盖重试、重定向和响应体读取。

## API 来源覆盖审计

运行 `python3 tools/compare_api_source_coverage.py`，只比较参考仓库 API 清单与本仓库 API 索引，生成 `sources/collected/api_source_coverage.json`。报告只保留名称和数量，不保存候选 URL，不请求参考 API，也不会修改 `apilinks.txt`。新来源必须逐项审核并经明确批准后才能导入。说明见 `docs/tools/compare_api_source_coverage.md`。

## 点播 API 命名快照

运行 `python3 tools/export_named_api_snapshots.py`，从 source_pipeline 已验证的本地 API 快照生成按接口名称命名的 JSON/XML 文件，并固定覆盖同一路径。输出包括 `sources/collected/api_named/index.json`、`list.txt` 和 `SUMMARY.txt`；失败时保留旧命名快照。说明见 `docs/tools/export_named_api_snapshots.md`。
