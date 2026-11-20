# test_compare_api_source_coverage.py 说明

## 用途
测试参考 API 清单解析、镜像去重、本地覆盖率计算和不导入约束。

## 覆盖范围
- 合并 API_LIST 与 API_MIRRORS。
- 同名镜像 URL 去重。
- 对照本地 API 索引和显式 apilinks 清单计算覆盖数量。
- 确认报告不包含原始 API URL，不标记任何来源已导入。
- 测试远端 JSON 响应和 HTTP 错误处理。

## 运行
python3 -m unittest tools.test_compare_api_source_coverage -v

主维护工作流通过 unittest discover 自动执行本测试。
