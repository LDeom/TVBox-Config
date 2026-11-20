# localize_tvbox_configs.py 说明

## 用途
为本仓库点播配置生成本地化副本，并安全下载配置中明确引用的文件依赖。

## 输入与输出
- 输入：sources/configs/vod/*.json
- 本地化配置副本：sources/collected/configs/
- 外部依赖缓存：sources/dependencies/external/<host>/
- 运行报告：output/reports/config_localization_report.json

## 支持的依赖类型
白名单：JS、JAR、PY、JSON、TXT、PNG、JPG、JPEG、GIF、WEBP、ZIP、APK、NODE。
黑名单：M3U、M3U8、XML。直播列表、XML 数据和普通媒体流不作为插件依赖下载。

## 下载与路径规则
- LDeom 自有仓库 raw URL 沿用现有 sources/js/、sources/jar/、sources/py/ 和 sources/dependencies/ 路径。
- 第三方依赖仅接受明确文件后缀的 HTTP(S) URL，按主机名和原始相对路径保存到 sources/dependencies/external/<host>/。
- 路径按 URL 解码后检查，拒绝 ..、反斜杠、空路径和越界路径。
- 同一主机、同一路径始终映射到同一文件名；URL 查询参数变化不会创建日期副本。
- 每日运行时第三方缓存会下载、校验后原子覆盖同一路径；失败时保留上次有效缓存。
- --no-refresh 可在手动运行时禁止刷新已存在的第三方缓存。

## 内容校验
- JSON：必须可解析（兼容仓库现有 JSON 注释清理规则）。
- JS/PY/TXT：必须是 UTF-8 文本。
- JAR：必须是有效 ZIP，且至少含一个 .class。
- ZIP：检查归档结构、文件数量、解压总量和 CRC。
- APK：除 ZIP 校验外，必须包含 AndroidManifest.xml。
- PNG/JPEG/GIF/WEBP：检查文件签名。
- NODE：只检查 ELF、PE 或 Mach-O 二进制签名。
- 单文件下载上限 32 MiB；归档解压总量上限 128 MiB。

## 安全边界
- 原始 sources/configs/vod/ 配置不会被修改；只生成 sources/collected/configs/ 副本。
- 外部依赖通过共享安全 HTTP 客户端下载，阻止局域网/本机 IP，并在重定向时重新校验目标地址。
- 下载内容不执行 JS、Python、JAR 或 NODE；只做字节、文本、归档和签名检查。
- 不会下载 M3U/M3U8/XML，也不会把视频流当作依赖。
- 不会删除原有配置、资源或失败时的旧缓存。

## 测试
运行 python3 -m unittest tools.test_config_localizer -v。
