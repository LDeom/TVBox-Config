# localize_tvbox_configs.py 说明

## 用途
为本仓库点播配置生成本地化副本，并处理明确引用的自有仓库资源依赖。

## 输入与输出
读取 `sources/configs/vod/*.json`，生成到 `sources/collected/configs/`，报告写入 `output/reports/config_localization_report.json`。

## 安全边界
- 原始配置保持不变。
- 仅处理允许的自有仓库 raw URL；第三方、代理和本机地址不自动下载。
- 缺失依赖下载前检查大小和格式；已有依赖默认不覆盖。
- 不执行 JS、Python 或 JAR。
