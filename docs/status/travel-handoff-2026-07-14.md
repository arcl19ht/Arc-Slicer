# Arc Slicer 旅行开发交接

## 交接基线

- 交接前可靠基线：`6af6ecd test(app): isolate facade Qt regression coverage`
- 工作分支：`feature/v2.5-multi-difficulty-export`
- 稳定分支：`main`，当前为 V2.4；不要把 V2.5-B 视为已完成版本。
- 自动化基线：`421 passed, 12 skipped, 89 subtests passed`。
- 已通过：`python -m compileall -q app.py external_merge.py arc_slicer`、`git diff --check`、`git diff --check 9044148..HEAD`。

## 已实现

- V2.5-B 已接入多难度发现、歌曲级选择、每难度 metadata、`base.ogg`/有效 `N.ogg` 试听选择，以及多 AFF/OGG 正式导出和单条聚合 songlist。
- 试听音源时长与 canonical `base.ogg` 时长已分离；所有实际导出音源会在 staging 前验证时长。
- 合法的 header-only AFF（例如 `AudioOffset:-30` 后接 `-`）可被发现、选择和导出。
- waveform worker 会持有到 `QThread.finished`；不变试听规格的 Space/播放按钮可暂停并原位恢复。
- `app.py` compatibility facade 已改用明确签名。其契约和真实 Qt 外部合并“选择目录”取消点击均在 subprocess 中测试，避免污染 Gate0 的替身 Qt 环境。

## 已通过自动化

- 全量 pytest：`421 passed, 12 skipped, 89 subtests passed`。
- facade 签名测试比较参数名、参数种类、默认值存在性和可比较的默认值；不再用 `*args`/`**kwargs` 吞掉 Qt `clicked(bool)`。
- subprocess 按钮回归覆盖外部合并目标目录选择的取消路径，确认无参数方法不会接收 `checked=False`。

## 尚未完成

- Windows 源码环境仍须人工复验外部合并目标目录选择器修复。
- 最终的 V2.5 难度 metadata UI 仍须 Windows 人工验收。
- 真实多 AFF/OGG 歌曲、导出矩阵，以及 current/library 从多难度缩减为少难度时旧文件清理，仍须真实数据验收。
- 不得把自动化测试替代真实 external merge；真实外部壳合并尚未执行。
- 仓库外截图尚未补齐；Windows EXE 也尚未为 V2.5-B 构建或验收。
- V2.5-C 尚未开始。Combo snapping 已取消；V2.6 只是后续候选，不在本次交接范围。

## 回家后第一步

```bash
git clone https://github.com/arcl19ht/Arc-Slicer.git
cd Arc-Slicer
git switch feature/v2.5-multi-difficulty-export
git pull --ff-only origin feature/v2.5-multi-difficulty-export
git rev-parse HEAD
git status --short
```

随后按 [macOS 开发说明](../setup/macos-development.md) 创建 Python 环境，先运行全量测试。确认工作树干净后，再优先执行未完成的 Windows/真实歌曲验收清单，而不是开始 V2.5-C。

## 不在 Git 中的数据

- `test_shell_songs/`、`ArcSlicerData/`、`out/`、`build/`、`dist/`、本地缓存和实际歌曲资产均不在 Git 中。
- 本地 `affintro.md` 是参考资料，也不保证存在于干净克隆。
- 不复制或提交私人 AFF、OGG、曲绘、外部壳目录或运行导出结果；在新机器上通过 UI 重新选择自己的歌曲目录。

## 恢复开发顺序

1. 在 macOS 上完成干净克隆、虚拟环境、依赖与全量测试。
2. 确认当前 feature 分支 HEAD 与远端一致，并阅读本文件、`AGENT.md` 和当前开发状态。
3. 完成 V2.5-B 的真实歌曲和 Windows 人工验收；需要外部壳时只执行明确批准的测试目标。
4. 依据验收结果更新 README、状态与计划文档，再评估 V2.5-C。
