# api_link_catalog.py 说明

## 用途
读取本仓库点播 API 地址清单，统一转换为内部记录格式，供 API 巡检、配置备份和源维护工具复用。

## 配置优先级
1. `apilinks.txt`：当前推荐格式，支持每行一个名称和一个或多个 URL；支持逗号、竖线和裸 URL。
2. `api_list.json`：仅当 TXT 清单不存在或没有有效记录时，回退读取旧版 `API_LIST` 和 `API_MIRRORS`。

## 安全边界
- 只解析 JSON 数据，不执行 `api_list.py` 等动态 Python 配置。
- 只接收 HTTP(S) URL；实际网络请求仍由 `fetch_util.py` 执行公网地址、重定向、超时和响应大小校验。
- 不会从参考仓库自动复制 API 地址。

## 更新规则
输入清单路径保持不变。自动生成的 API 缓存和索引按原文件名、原路径覆盖更新；失败时保留已有有效缓存，不创建日期版本副本。

## 测试
`python3 -m unittest tools/test_api_link_catalog.py`
