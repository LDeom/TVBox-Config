# export_tvbox_vod_config.py

## 用途

从本仓库 `sources/collected/api_index.json` 生成单一、可导入 TVBox 的点播配置，输出固定覆盖到：

- `sources/collected/tvbox_vod_config.json`
- `sources/collected/tvbox_vod_config_summary.txt`

## 纳入规则

仅纳入同时满足以下条件的 API：

1. `type=1`（MacCMS 类 JSON API）。
2. API 索引状态为“有效影视 JSON”。
3. 本地 `saved_file` 存在且再次通过 `valid_vod_payload` 校验。
4. API URL 为公开 HTTP(S) 形式，且不是 XML 路径。
5. 同一个 API URL 只纳入一次。

优先选择镜像推荐线路；如果推荐线路不是有效 JSON，则从有效 JSON 候选中按响应时间选择。生成 TVBox 站点时移除探测用的 `ac=list` 参数，保留其他查询参数，避免把列表探测模式固定写入正式配置。

## 输出格式

配置包含 `sites`、空的 `parses` 和 `lives`。站点包含 `key`、`name`、`type`、`api`、搜索和筛选能力字段。不会把 XML API、type=0 自定义爬虫、直播源或参考仓库完整配置导入。

## 执行

```bash
python3 tools/export_tvbox_vod_config.py
python3 -m unittest tools/test_export_tvbox_vod_config.py
```

## 安全与更新

不执行远程代码、不下载参考仓库配置、不修改原始配置。输出路径固定，每日更新覆盖原文件，不生成历史版本。若本轮没有任何有效 API，则报错并保留旧输出。影视 JSON 结构有效不代表每个播放地址都能播放。
