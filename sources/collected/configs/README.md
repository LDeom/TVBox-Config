# 本地化 TVBox 配置

以下文件是从本仓库 `sources/configs/vod/` 生成的可导入 JSON 副本。原始配置未被修改。

## 配置链接

| 配置 | 导入链接 |
|---|---|
| 0821 | https://raw.githubusercontent.com/LDeom/TVBox-Config/main/sources/collected/configs/0821.json |
| 0825 | https://raw.githubusercontent.com/LDeom/TVBox-Config/main/sources/collected/configs/0825.json |
| 0826 | https://raw.githubusercontent.com/LDeom/TVBox-Config/main/sources/collected/configs/0826.json |
| 0827 | https://raw.githubusercontent.com/LDeom/TVBox-Config/main/sources/collected/configs/0827.json |
| 367 | https://raw.githubusercontent.com/LDeom/TVBox-Config/main/sources/collected/configs/367.json |
| 9918 | https://raw.githubusercontent.com/LDeom/TVBox-Config/main/sources/collected/configs/9918.json |
| 99188 | https://raw.githubusercontent.com/LDeom/TVBox-Config/main/sources/collected/configs/99188.json |
| dianshi | https://raw.githubusercontent.com/LDeom/TVBox-Config/main/sources/collected/configs/dianshi.json |
| fty | https://raw.githubusercontent.com/LDeom/TVBox-Config/main/sources/collected/configs/fty.json |
| js | https://raw.githubusercontent.com/LDeom/TVBox-Config/main/sources/collected/configs/js.json |
| jsm | https://raw.githubusercontent.com/LDeom/TVBox-Config/main/sources/collected/configs/jsm.json |

## 本地化边界

- 只读取本仓库的配置文件，不下载外部完整配置，不覆盖原始 JSON。
- 仅自动本地化 LDeom 自有 GitHub 仓库中明确引用的依赖。
- 已存在的依赖不自动覆盖；缺失文件先校验，再写入本仓库。
- 第三方域名、代理地址、本机地址和无法验证的文件继续保留原地址。
- 这些配置副本仍可能含有未本地化的外部依赖；导入前可查看 [本地化报告](https://github.com/LDeom/TVBox-Config/blob/main/output/reports/config_localization_report.json)。
