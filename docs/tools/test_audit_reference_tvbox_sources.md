# test_audit_reference_tvbox_sources.py 说明

## 用途
测试参考 TVBox 配置审计器的 JSON 解析、站点 API 提取、去重及安全追加行为。

## 覆盖范围
- 识别含 sites 数组的 TVBox 配置，拒绝普通影视列表 JSON。
- 只提取 type 0/1 和绝对 HTTP(S) API 地址。
- type 1 测试地址正确追加 ac=list。
- 相同 API URL 去重并保留多个来源信息。
- 追加时保留 apilinks.txt 原有内容，不重复写入 URL。
- 输出名称稳定，避免逗号和竖线破坏清单格式。

## 运行
```bash
python3 -m unittest discover -s tools -p 'test_audit_reference_tvbox_sources.py' -v
```
