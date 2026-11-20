# 本地化点播配置

此目录保存从上游 `LDeom/tvbox` 同步并改写过插件引用的 11 份 TVBox 配置。

## 配置文件

`jsm.json`、`js.json`、`0826.json`、`0827.json`、`fty.json`、`0825.json`、`0821.json`、`dianshi.json`、`367.json`、`9918.json`、`99188.json`。

## 插件引用规则

- 配置中已存在于本仓库的 JS 插件，统一引用 `sources/js/` 下的文件。
- 配置中已存在于本仓库的 JAR 插件，统一引用 `sources/jar/` 下的文件。
- 其他辅助文件（例如 JSON、TXT、M3U、PY）暂时使用上游仓库的 raw 地址，不伪装成本仓库文件。
- 上游缺失的 `js/西门[V2].js` 无法本地化，已在依赖清单中保留缺失记录。

## 总配置入口

`sources/vod/TVBox_点播总配置.json`、`config.json` 和 `tvbox-config.json` 中对应的 11 个入口均已改为本仓库 `sources/configs/vod/` 下的配置地址。

## 自动同步

执行 `python3 tools/sync_plugins.py` 可重新同步插件、生成依赖清单、改写配置并更新总配置入口。GitHub Actions 已配置自动提交这些改动。

依赖路径、文件大小、SHA-256 和改写统计见 `output/reports/plugin_dependency_manifest.json`。
