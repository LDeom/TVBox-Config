# test_fetch_util.py 说明

## 用途
测试共享 HTTP 客户端的主机级熔断器和单 URL 总请求预算。

## 覆盖范围
- 连续失败达到阈值后打开熔断。
- 冷却结束后仅允许一个半开探测。
- 探测成功关闭熔断，探测中止释放半开锁。
- 不同主机的熔断状态相互隔离。
- HTTP 429/5xx 计入失败，普通 404 不视为主机不可达。
- SafeFetcher 在服务器错误后阻止继续请求。
- 响应体读取阶段也执行总请求截止时间。

## 运行
python3 -m unittest tools.test_fetch_util -v

主维护工作流通过 unittest discover 自动执行本测试。
