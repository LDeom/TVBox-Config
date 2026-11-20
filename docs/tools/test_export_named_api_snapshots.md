# test_export_named_api_snapshots.py 说明

## 用途
测试点播 API 命名快照导出器的镜像选择、稳定路径、覆盖和失败缓存保护。

## 覆盖范围
- 多镜像按优选线路导出。
- 输出文件名由接口 key/name 稳定生成。
- 更新时覆盖同一路径，不生成历史副本。
- 新一轮失败时保留旧命名快照。
- 拒绝越界 saved_file 路径。

## 运行
python3 -m unittest tools.test_export_named_api_snapshots -v

主维护工作流通过 unittest discover 自动执行本测试。
