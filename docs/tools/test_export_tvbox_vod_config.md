# test_export_tvbox_vod_config.py

## 用途

验证 `export_tvbox_vod_config.py` 的 TVBox 点播配置生成规则。

## 覆盖场景

- 只纳入原配置 type=1，或来自 apilinks.txt 且已验证为有效影视 JSON、并且本地缓存复验通过的 API。
- apilinks.txt 的内部 type 标记不作为 TVBox 解析器类型；通过验证后统一输出为 TVBox type=1。
- 排除 XML、type=0、自身缺少缓存的 API。
- 优先选择推荐 JSON 镜像。
- 对重复 API URL 去重。
- 拒绝结构无效的本地缓存。
- 验证固定输出路径及摘要文件生成。

## 执行

```bash
python3 -m unittest tools/test_export_tvbox_vod_config.py
```
