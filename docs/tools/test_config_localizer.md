# test_config_localizer.py 说明

## 用途
对 tools/localize_tvbox_configs.py 的依赖识别、路径映射、内容校验、配置引用替换和缓存更新逻辑执行离线单元测试。

## 覆盖范围
- 自有 GitHub URL 识别与第三方 URL 白名单。
- 文件后缀白名单、M3U/M3U8/XML 黑名单。
- URL 解码后的路径穿越防护。
- 第三方主机隔离、稳定缓存路径和查询参数变化时路径不变。
- spider、wallpaper、logo、sites.api/ext 等依赖提取。
- 递归替换配置引用，同时确认原始配置对象不被修改。
- JSON、UTF-8 文本、JAR、ZIP、APK、图片和 NODE 文件签名校验。
- 下载成功时原子覆盖缓存，下载失败时保留旧缓存。

## 运行
在仓库根目录执行：

python3 -m unittest tools.test_config_localizer -v

主维护工作流会通过 unittest discover 自动运行本测试。
