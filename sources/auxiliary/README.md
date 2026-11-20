# 辅助配置资源库说明

本目录作为辅助资源分类入口，不复制或搬迁现有资源文件。为保证原有配置引用不失效，所有资源继续保留在原来的文件名和路径；资源清单通过 `tools/build_resource_catalog.py` 统一生成。

## 分类与现有位置

| 资源类型 | 当前可检索位置 | 当前情况 |
|---|---|---|
| 书源/阅读 | `sources/dependencies/LDeom-tvbox/json/`、`sources/js/` | 已发现少量阅读/电子书相关文件，尚未形成独立书源集合 |
| 音源/听书 | `sources/js/`、`sources/py/` | 已发现听书、音乐、电台、相声等脚本；未逐一验证可用性 |
| 漫画/动漫 | `sources/js/`、`sources/dependencies/` | 有动漫类脚本；独立漫画源数量及可用性仍需检查 |
| 弹幕 | `sources/js/`、现有 JSON 配置 | 仅按名称命中少量候选，尚未确认存在完整、独立的弹幕资源库 |
| 点播模板/混排 | `sources/vod/`、`sources/configs/vod/` | 现有 TVBox 配置中包含相关结构，尚未拆分成独立模板库 |
| 站点域名分组/推荐 | 现有点播配置及采集报告 | 可从本地配置提取站点信息，但尚未建立独立维护的数据集 |
| 直播资源 | `sources/live/`、`sources/collected/live_backups/` | 已有直播配置、列表和逐源备份 |

## 更新规则

1. 不从参考仓库自动复制 `cy/` 下的文件或远程资源。
2. 不复制已有资源到新目录，不改变原文件名和路径。
3. 每日资源索引直接覆盖 `sources/collected/resource_catalog.json`。
4. 新增资源必须先验证格式、来源和许可，再登记到本仓库。
5. 文件被索引不代表接口有效、配置可导入或内容可播放。

## 资源索引

- 生成脚本：`tools/build_resource_catalog.py`
- 自动生成文件：`sources/collected/resource_catalog.json`
- 脚本说明：`docs/tools/build_resource_catalog.md`

当前分类是基于目录、扩展名和文件名的初步归类，不等同于内容级审核。

## 参考资源差异报告

- 对比工具：tools/compare_auxiliary_resources.py
- 报告：sources/collected/auxiliary_resource_comparison.json
- 该工具只读取参考仓库 cy/ 目录清单元数据（文件名、路径、大小和 SHA），不下载或导入参考 JSON 内容。
- 报告中的“同类候选”仅表示本仓库索引中存在同类别文件，不代表资源功能等价、可导入或可用。
- 如果后续要实际导入某个资源，应先单独审核其格式、来源、许可、依赖和安全性，再明确批准导入。
