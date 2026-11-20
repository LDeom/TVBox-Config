# audit_reference_tvbox_sources.py 说明

## 用途
检查参考仓库的 TVBox 配置订阅地址，读取配置中的 `sites`，再逐个验证其中真正的点播 API。参考仓库清单中的 76 个地址是 TVBox 配置入口，不是可直接写入本仓库 `apilinks.txt` 的 VOD API；因此本工具先解析配置，再提取真实站点 API。

## 处理流程
1. 下载参考仓库 `api_list.json`，合并 API_LIST 与 API_MIRRORS，并按 URL 去重。
2. 请求每个配置入口，要求返回含 `sites` 数组的 TVBox JSON 配置。
3. 只提取 `sites` 中 type 0/1 且 api 为绝对 HTTP(S) 地址的项目。
4. type 1 按 TVBox 常见规则追加 `ac=list`；type 0 保持原始 API URL。
5. 对提取出的 API 逐一请求，必须通过影视 JSON/XML 数据校验才算有效。
6. 只把有效 API 追加到 `apilinks.txt`；已有内容和注释原样保留，已存在 URL 不重复写入。
7. 固定覆盖 `sources/collected/reference_tvbox_source_audit.json`，不生成日期副本。

## 安全边界
- 所有网络请求复用 `fetch_util.py`，执行公网 IP 校验、逐跳重定向校验、主机熔断、响应大小限制和单 URL 总时间预算。
- 不执行参考配置中的 JS、JAR、PY 或其他远程代码。
- 不导入参考仓库原始配置，不覆盖或删除本仓库原始配置。
- 仅导入通过有效影视 JSON/XML 校验的 API。
- 最多测试 1000 个去重后的实际站点 API；若超出会在报告中明确标记截断。

## 运行
```bash
python3 tools/audit_reference_tvbox_sources.py
```

## 输出
- `apilinks.txt`：只追加通过验证的新 VOD API。
- `sources/collected/reference_tvbox_source_audit.json`：配置入口检查、站点 API 测试结果和新增数量。
