# TVBox-Config

TVBox 点播配置、直播源及自动巡检工具仓库。

- [仓库目录与检测标准](docs/REPOSITORY_STRUCTURE.md)
- 点播源：`sources/vod/`
- 本地化点播配置：`sources/configs/vod/`
- 直播源：`sources/live/`
- JS/JAR 插件：`sources/js/`、`sources/jar/`
- 自动采集与聚合结果：`sources/collected/`
- 检测工具：`tools/`
- 检测输出与历史：`output/`

## 自动维护

GitHub Actions 每日执行本仓库 JSON 检查、点播 API 巡检、直播列表提取、采集站/Py 站聚合和在线配置包索引。

- [自动维护工作流](.github/workflows/maintain-local-json.yml)
- [源处理主程序](tools/source_pipeline.py)
- [统一 HTTP 抓取工具](tools/fetch_util.py)
- [生成结果目录](sources/collected/)
- [运行报告](output/reports/source_pipeline_report.json)
- [Actions 执行记录](https://github.com/LDeom/TVBox-Config/actions)

数据定义只从本仓库已有配置中提取；远程请求只访问这些配置明确声明的 API/直播列表地址，不会用其他仓库的 JSON 覆盖本仓库配置。失败的 API 不会覆盖或删除上一份有效缓存。

注意：文件被收录、HTTP 请求成功、返回影视数据结构有效、实际播放成功是不同验证等级。直播列表解析成功也不代表每条流都能播放；请以报告中的状态和检测等级为准。
