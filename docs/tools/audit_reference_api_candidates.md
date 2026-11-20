# audit_reference_api_candidates.py 说明

## 用途
逐项验证参考仓库 `lubin776/tvbox-api-backup/api_list.json` 中的订阅候选。配置类 URL 仅作为 JSON 数据读取，再提取其中 type 0/1 的站点 API；疑似直接 VOD API 则直接探测。

## 验证规则
- 每个候选配置和提取出的 VOD API 均使用统一公网 URL 校验、请求超时和响应大小限制。
- 只有真实请求返回 2xx，且 `source_pipeline.valid_vod_payload` 能识别影视列表及影视字段的 JSON/XML，才可加入 `apilinks.txt`。
- 仅返回 HTTP 200、普通 JSON、TVBox 配置、HTML 或空列表均不视为有效 VOD API。
- 不执行配置中的 JS/Python/JAR，不导入完整配置或直播源。
- 清单只追加新验证通过的 URL；按规范化 URL 去重，不覆盖已有行。

## 输出
- 输入：参考仓库 `api_list.json`。
- 清单：`apilinks.txt`（仅追加有效 API）。
- 报告：`sources/collected/api_candidate_validation.json`，记录每个候选配置和每个 API 的测试状态。
- 每次运行覆盖同一报告路径，不生成历史版本。

## 运行
```bash
python3 tools/audit_reference_api_candidates.py --workers 5
python3 -m unittest tools/test_audit_reference_api_candidates.py
```

注意：影视 API 返回有效列表不等于其每个播放地址都能实际播放。
