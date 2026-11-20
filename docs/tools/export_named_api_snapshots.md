# export_named_api_snapshots.py 说明

## 用途
把 source_pipeline 已验证的点播 API 快照按接口名称输出为稳定文件，生成清单和摘要。

## 输入与输出
- 输入：sources/collected/api_index.json 及其中 saved_file 指向的本地有效快照。
- 命名快照：sources/collected/api_named/<接口名>_<稳定ID>.json 或 .xml。
- 索引：sources/collected/api_named/index.json。
- 列表：sources/collected/api_named/list.txt。
- 摘要：sources/collected/api_named/SUMMARY.txt。

## 更新规则
- 稳定 ID 只由接口 key/name 生成，不随 URL 或日期变化。
- 每日成功时覆盖同一接口的同一路径，不生成日期副本。
- 多镜像优先采用 mirror_recommendations 中的优选有效线路。
- 当前轮次失败时保留上次命名快照；无历史缓存时仅在报告中标记失败。
- 不修改原始配置，不重新请求 API，不执行远程代码。

## 校验
导出前再次调用 source_pipeline 的影视 JSON/XML 校验逻辑，拒绝无效或越界的本地快照。

## 运行
python3 tools/export_named_api_snapshots.py
