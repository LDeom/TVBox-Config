# compare_auxiliary_resources.py 说明

## 用途
对比参考仓库 lubin776/tvbox-api-backup 的 cy/ 辅助资源目录与本仓库资源索引，生成类别覆盖差异报告。

## 输入与输出
- 远端输入：GitHub cy/ 目录清单元数据（文件名、路径、SHA、大小、网页地址）。
- 本地输入：sources/collected/resource_catalog.json。
- 输出：sources/collected/auxiliary_resource_comparison.json。

## 安全边界
- 只读取参考仓库目录列表，不下载任何参考 JSON 文件内容。
- 不复制、导入或执行远程资源。
- 只用本仓库资源索引做类别候选比较；同类候选不代表功能等价或可用。
- GitHub 元数据暂不可用时保留已有报告，不覆盖成空报告。

## 更新规则
主维护工作流每日执行，直接覆盖固定报告路径，不生成日期副本。

## 运行
python3 tools/compare_auxiliary_resources.py
