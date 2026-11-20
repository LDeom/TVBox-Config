# backup_tvbox_configs.py 说明

## 用途
读取 `apilinks.txt`（或安全兼容的旧格式清单），按同名镜像顺序回退，备份返回的 TVBox JSON 配置。

## 输出
- `sources/collected/api_backups/raw/`：原始解码 JSON。
- `sources/collected/api_backups/portable/`：相对资源 URL 绝对化副本。
- `sources/collected/api_backups/index.json`、`list.txt`：固定路径索引。
- `output/reports/api_backup_report.json`：备份状态报告。

## 更新规则
同一清单项每日覆盖原文件名和路径，不生成日期副本或历史版本。原始配置不被改写；不下载或执行配置中引用的 JS/JAR。
