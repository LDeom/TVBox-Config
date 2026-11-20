# build_resource_catalog.py 说明

## 用途
扫描本仓库已有的辅助资源和配置文件，生成统一资源清单，便于判断书源、音源、漫画、弹幕、直播、点播配置及插件依赖的实际收录情况。

## 输入范围
只扫描以下本地目录：`sources/dependencies/`、`sources/js/`、`sources/jar/`、`sources/py/`、`sources/live/`、`sources/vod/`、`sources/configs/vod/`、`sources/pending/`。

## 输出
固定覆盖 `sources/collected/resource_catalog.json`。每日运行不更改文件名和路径，不创建日期目录或历史副本。

## 安全边界
- 不访问参考仓库或其他外部资源库。
- 不下载资源，不执行 JS、Python 或 JAR。
- 仅记录相对路径、扩展名、文件大小和初步分类。
- 文件被收录不等于链接有效、配置可导入或内容可播放。

## 手动运行
```bash
python3 tools/build_resource_catalog.py
python3 -m unittest tools/test_resource_catalog.py
```
