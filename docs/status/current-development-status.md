# Arc Slicer 当前开发状态

## 文档范围

- 文档对应分支：`feature/v2.4-audio-audition`
- 稳定基线：`main` 的 V2.3
- V2.3 截止提交：`8316bba feat(v2.3): add timeline quick draft gesture`
- V2.4-A rebase 后的代码提交：`bf3be77 fix(v2.4): handle Qt multimedia enum states`
- 测试基线：374 passed，12 skipped

V2.4-A 的三个功能提交因本地 rebase 到 V2.3 文档基线而获得新 hash；当前文档提交位于它们之后。历史需求书和 V2.3 实施计划保留其当时的设计上下文，不作为当前状态判断依据。

## 已经实现

### V2.2

- AFF 与 `base.ogg` 切片、任意正数倍速和片段级倍速覆盖。
- `current_export` 与 `library_export` 双层导出，songlist/packlist、曲包封面和固定 section 选项。
- 外部目标壳 `songs` 根目录的安全合并：选择并验证目标、检查计划、显式确认、受影响内容备份、manifest、失败恢复和目标目录记忆。

### V2.3

- `WaveformData`、波形缓存、波形/时间标尺/timeline lanes 显示。
- 空白区拖拽创建片段、端点拖拽修改、草稿预览和 Ctrl+单击快速草稿。
- 卡片与时间线的 selected/hovered 联动，自动/手动排序。
- `uid` 与 `link_group_id`，断链、重连和级联端点编辑。
- 片段撤销/重做，以及 Delete、Backspace、Ctrl+S、Ctrl+D 快捷键。

## 正在开发

V2.4-A 音频试听位于独立分支 `feature/v2.4-audio-audition`，不包含在 `main` 中。已实现对当前选中的完整片段使用源 `base.ogg` 手动试听：播放/暂停/恢复、循环开关、空格快捷键、有效倍速、播放头显示，以及切换片段时停止旧播放。试听不生成临时切片，播放状态不写入撤销历史，也不标记导出 dirty。

## 尚待人工验收

- V2.4-A 的真实声音、有效倍速和循环边界。
- 打包 EXE 中的 OGG 试听。

## 尚未实现

- 边界修改后的自动试听和 150--300ms 自动试听防抖。
- Combo snapping、多难度切片和谱面预览。

V2.4-A 不是完整 V2.4 完成版本；在上述人工验收和后续范围完成前，不应将 V2.4 标记为完成。

## 文档更新规则

每次版本收口后，同步更新 `README.md`、`AGENT.md` 和本文档，并明确区分“已经实现”“正在开发”“尚待人工验收”“尚未实现”。
