# JAR / JS 插件依赖检查报告

- 检查日期：2026-11-20
- 配置来源：`LDeom/tvbox` 的 `master` 分支
- 检查配置：`jsm.json`、`js.json`、`0826.json`、`0827.json`、`fty.json`、`0825.json`、`0821.json`、`dianshi.json`、`367.json`、`9918.json`、`99188.json`
- 检查方法：解析配置内以 `./` 开头的本地 JAR/JS 引用，并与上游仓库递归文件树比对；URL 编码路径先解码再比对。

## 统计

| 项目 | 数量 |
|---|---:|
| 去重后的本地依赖引用 | 243 |
| JAR 引用 | 5 |
| JS 引用 | 238 |
| 在上游仓库中找到 | 242 |
| 上游仓库中未找到 | 1 |

## 确认缺失

| 配置 | 引用路径 | 状态 |
|---|---|---|
| `js.json` | `./js/西门[V2].js` | 上游 `LDeom/tvbox` 的 master 文件树中未找到 |

建议：先检查 `js.json` 是否仍需要“西门[V2]”站点。若需要，应从可信来源补齐脚本并验证兼容性；若已废弃，应从配置中删除该站点引用。不能用空文件代替插件。

## 已核对的 JAR

以下 5 个 JAR 路径均在上游文件树中存在：
- `jar/spider.jar`
- `jar/pg_upgraded.jar`
- `jar/pg23a94bb_upgraded.jar`
- `jar/custom_spider.jar`
- `jar/XBPQ_upgraded.jar`

## 重要说明

当前 `LDeom/TVBox-Config` 仓库的 `sources/js/` 与 `sources/jar/` 目前只有说明文件，没有实际插件二进制/脚本文件。因此，若计划让 TVBox-Config 独立托管所有插件，243 个被引用依赖都尚未复制进本仓库。

但这些配置目前引用的是 `LDeom/tvbox` 上的配置文件；其中 `./jar/...`、`./js/...` 等相对路径应由原配置所在仓库提供。不能仅因 TVBox-Config 未镜像，就判定原配置无法加载。

本报告只验证文件是否存在于上游 Git 文件树，不代表插件运行兼容、接口可用或播放成功。外部绝对 URL 引用及配置中的内置 `csp_*` 类不计入上述 243 个本地依赖。
