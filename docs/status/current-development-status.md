# Arc Slicer 当前开发状态

## 文档范围

- 文档对应分支：`feature/ui-clarity-refresh`
- 稳定基线：`main` / `origin/main` = `96e0381`
- V2.3 截止提交：`8316bba feat(v2.3): add timeline quick draft gesture`
- V2.4-B 分支起点：`f2186e8`
- V2.4-B 代码提交：`99d0b65 feat(v2.4): add debounced automatic audition`
- UI 清晰度改造：进行中；只调整视觉表达与控件层级，不改业务语义
- 测试基线：369 passed，12 skipped，75 subtests passed

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

## 已实现

V2.4-A 已合入 `main`：对当前选中的完整片段使用源 `base.ogg` 手动试听，支持播放/暂停/恢复、循环、空格、有效倍速、播放头与切换片段停止旧播放。

V2.4-B 已实现：默认关闭且不持久化的自动试听开关；正式区间/有效倍速提交后的 200ms 防抖；连续提交最后一次生效；输入、拖动和手动播放期间取消 pending。自动试听不生成临时切片，不进入撤销历史，不标记导出 dirty。

## 当前开发：UI 清晰度与视觉层级

- 统一主题 token 和全局 QSS，避免裸 `QFrame` 选择器将卡片边框继承到 `QLabel`。
- 强化输入框、下拉框、开关、播放工具栏、片段卡片、导出与外部合并操作的静态可识别性。
- 自动排序关闭映射为手动顺序；旧 `sort_mode="manual"` 兼容映射为关闭自动排序，不改变片段顺序结果。
- 不改变切片/导出数据结构、播放/循环/自动试听语义，亦不改变 dirty 或撤销历史。

## 尚待人工验收

- Windows 中文字体下的最终 UI 视觉、100%/125%/150% 缩放与打包 EXE。
- V2.4-B 连续切点修改、倍速、循环边界与快速操作的真实听感。
- 打包 EXE 中的 OGG 自动试听。

## 尚未实现

- Combo snapping、多难度切片和谱面预览。

完成 UI 人工视觉验收后，下一阶段为 V2.4-C Windows EXE 与 OGG 稳定性专项。V2.4 仍不应在上述人工验收完成前标记为完整完成版本。

## 文档更新规则

每次版本收口后，同步更新 `README.md`、`AGENT.md` 和本文档，并明确区分“已经实现”“正在开发”“尚待人工验收”“尚未实现”。
