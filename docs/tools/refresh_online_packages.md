# refresh_online_packages.py 说明

## 用途
只处理根目录 `rylinks.txt` 明确登记的在线配置包 URL，下载后解析 JSON 并生成本地索引。

## 输出
更新 `sources/collected/packages/`、`sources/collected/online_package_download_index.json` 和 `output/reports/` 报告。

## 更新规则
成功时覆盖同一 URL 对应的固定缓存路径；失败时保留旧文件。不执行包内 JS、Python 或 JAR。
