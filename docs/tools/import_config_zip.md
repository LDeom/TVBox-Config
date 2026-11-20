# import_config_zip.py 说明

## 用途
对用户明确提供的 ZIP 配置包做安全校验，并将文件隔离解压到 `imports/staging/`。不会将内容自动合并进正式 TVBox 配置目录。

## 输入
- 本地文件：`python3 tools/import_config_zip.py --zip path/to/package.zip`
- 手动指定公开 URL：`python3 tools/import_config_zip.py --url https://example.com/package.zip`

## 安全限制
- ZIP 最大 20 MiB；最多 200 个条目；单文件最大 8 MiB；解压总量最大 40 MiB；压缩率不超过 100。
- 拒绝绝对路径、路径穿越、Windows 路径、符号链接、设备文件、加密 ZIP、重复路径和不支持的压缩算法。
- 仅接受 JSON、TXT、M3U、XML、JS、PY、JAR、常见图片和 Markdown 文件；拒绝 APK、EXE、脚本安装器等可执行安装包。
- JSON 文件必须能解析；JS、Python 和 JAR 只作为静态文件保存，绝不执行。
- 只写入 `imports/staging/`，不覆盖 `sources/`、`tools/`、`.github/` 或 `output/`。
- 暂存目录已有同名文件时拒绝导入，防止覆盖旧内容。

## 输出
- `imports/staging/manifest.json`：文件路径、大小和 SHA-256。
- `output/reports/zip_import_report.json`：本次导入结果；固定路径覆盖更新。

## 注意
导入暂存成功不代表配置已经适配 TVBox。必须人工检查来源、依赖、许可证和内容，再决定是否手动纳入正式配置。
