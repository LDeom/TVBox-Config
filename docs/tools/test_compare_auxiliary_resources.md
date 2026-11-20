# test_compare_auxiliary_resources.py 说明

## 用途
测试辅助资源对比工具的目录元数据过滤、类别映射和本地候选报告逻辑。

## 覆盖范围
- 只接受 cy/ 目录下的 JSON 文件元数据。
- 忽略目录、其他目录文件和非 JSON 文件。
- 检查 GitHub API 响应结构。
- 对比本地资源类别并标记候选数量。
- 确认报告明确标记不导入、不下载参考内容。

## 运行
python3 -m unittest tools.test_compare_auxiliary_resources -v

主维护工作流通过 unittest discover 自动执行本测试。
