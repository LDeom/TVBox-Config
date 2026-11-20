# test_source_pipeline.py 说明

## 用途
对 source_pipeline.py 的离线解析、点播数据识别、直播列表解析、URL 套壳展开、镜像排序和 TVBox 聚合输出进行单元测试。

## 覆盖范围
- JSON 注释与尾逗号清理。
- M3U/TXT 直播列表解析和 JSON 频道展开。
- Base64、GZIP、JSONP、2423-AES 等点播响应处理。
- 直播 URL 递归套壳、循环检测和最大展开深度。
- API 镜像健康排序。
- rylinks 清单和在线 JSON 包解析。
- 公网地址校验。
- TVBox 逐源 lives 聚合：优先使用成功备份、失败时保留旧备份、无缓存时回退原始 URL，并保留总 M3U 入口。

## 运行
在仓库根目录执行：

python3 -m unittest tools.test_source_pipeline -v

主维护工作流通过 unittest discover 自动执行本测试。
