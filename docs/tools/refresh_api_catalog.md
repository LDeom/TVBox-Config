# refresh_api_catalog.py 说明

## 用途
巡检 API 清单中的线路，调用统一安全 HTTP 层和影视数据结构解析，按有效性与响应耗时生成镜像推荐。

## 输出
更新 `sources/collected/api_index.json`、镜像推荐配置及 `output/reports/` 巡检报告。

## 注意
推荐结果只是线路评分，不会自动改写原始 TVBox 配置；HTTP 成功不代表返回有效影视数据。
