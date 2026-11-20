# compare_api_source_coverage.py 说明

## 用途
对照参考仓库 api_list.json 与本仓库 API 索引，统计来源覆盖差距，生成只含名称和数量的候选审计报告。

## 输入与输出
- 参考输入：lubin776/tvbox-api-backup 的 api_list.json。
- 本地输入：sources/collected/api_index.json、apilinks.txt。
- 输出：sources/collected/api_source_coverage.json。

## 安全边界
- 只下载并解析参考 API 清单文件，不请求其中任何 API endpoint。
- 报告只保存接口名称、覆盖数量和状态，不复制参考 URL。
- 不修改 apilinks.txt，不自动添加任何 API 来源。
- 新来源须逐项验证可用性和许可，并经用户明确批准后才可加入本仓库清单。
- 参考清单不可用时保留已有报告，不覆盖为空报告。

## 更新
主维护工作流每日运行，覆盖固定报告路径，不生成日期副本。

## 运行
python3 tools/compare_api_source_coverage.py
