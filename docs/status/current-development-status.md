# Arc Slicer 当前开发状态

## 文档范围

- 当前稳定版本：V2.4
- V2.3 截止提交：`8316bba feat(v2.3): add timeline quick draft gesture`
- V2.4 最终文档提交：`47c1f8a docs: document timeline seek and translation gestures`
- 测试基线：378 passed，12 skipped，75 subtests passed。

历史需求书和 V2.3 实施计划保留其当时的设计上下文，不作为当前状态判断依据。

## V2.2 已完成

- AFF 与 `base.ogg` 切片、任意正数倍速和片段级倍速覆盖。
- `current_export` 与 `library_export`、songlist/packlist、曲包封面和固定 section 选项。
- 外部目标壳 `songs` 根目录的安全合并：验证目标、检查计划、显式确认、备份、manifest、失败恢复和目标目录记忆。

## V2.3 已完成

- `WaveformData`、波形缓存、波形/时间标尺/timeline lanes。
- 空白区拖拽创建、端点编辑、草稿预览和 Ctrl+单击快速草稿。
- 卡片与时间线 selected/hovered 联动，自动/手动排序。
- `uid` 与 `link_group_id`，断链、重连和级联区间编辑。
- 撤销/重做，以及 Delete、Backspace、Ctrl+S、Ctrl+D 快捷键。

## V2.4 已完成

### V2.4-A 手动试听

- 使用源 `base.ogg` 对完整选中片段播放、暂停和恢复。
- 支持循环、有效倍速、空格快捷键和波形播放头。
- 不生成临时试听音频，不影响 AFF、导出、dirty 或历史。

### V2.4-B 防抖自动试听

- 自动试听默认关闭且不持久化。
- 正式编辑提交后按 200ms 防抖安排试听。
- 显式选择完整卡片或时间线片段同样安排试听；快速连续选择只播放最后一个片段。
- 手动播放、输入编辑、拖动、删除、切歌和关闭窗口均取消 pending。

### V2.4-C EXE/OGG 稳定性与时间线交互

- 修复显式选择片段未安排自动试听的问题。
- 修复时间线选择推动主页面跳到对应卡片的问题。
- 未选中时间线片段首次点击只选择和高亮；自动试听开启时从片段起点试听，主页面不滚动。
- 短点击已选中片段会定位播放头并立即播放，不修改区间、dirty 或历史。
- 拖动已选中片段主体会整体平移，保持长度、限制音频边界、同步级联组，并只提交一次历史；最终状态只自动试听一次。
- endpoint handle 继续优先于主体点击和平移；循环到终点仍回到完整片段的原始起点。

### UI Clarity

- 自动排序、循环和自动试听使用真实 switch；表单与导出选择使用方形勾选框。
- 主按钮、禁用态、下拉箭头和播放工具栏的视觉语义已完成 Windows 源码环境人工验收。

## 人工验收

- Windows 源码环境听感验收通过。
- Windows 源码环境 UI 视觉验收通过。
- Windows EXE 最终人工验收通过，包括真实 OGG 播放、手动/自动试听、循环、倍速、选择防抖、定位播放、整体及级联平移、撤销/重做与 viewport 稳定性。
- 最终 EXE 构建成功，SHA-256：`6F314CDB5DE1F479E1F06A506A63B7BC29C5D8D93BB7278307E5FEACF56B37F9`。

## 当前开发：V2.5-A 多难度基础与兼容模型

V2.5-A 只做格式和兼容审计、难度发现与用户多选模型、slides 持久化及迁移设计、缺失/未知难度行为和 songlist difficulties 数据模型设计。旧 slides 必须默认继续使用 `2.aff`。当前不实现多 AFF 切片或 UI，也不假定难度仅为 0–3。

V2.5-B 将负责难度选择 UI、持久化、多 AFF 切片、多难度导出和 songlist difficulties；V2.5-C 将负责缺失难度、真实歌曲、外部测试壳与 Windows EXE 验收。每个片段/倍速的 `base.ogg` 必须只切一次，既有 segment export ID 和 external merge 安全边界保持不变。

## 已取消 / 不计划

Combo snapping 已取消，原因是当前用户需求和实际收益不足。近期不实现 combo 时间解析、端点吸附、snapping UI 或 snapping 配置；除非未来出现新的明确用户需求，不得自行恢复。

## 远期候选

- 谱面预览：等待独立需求评估，不承诺版本号。

## 尚未实现

- 多难度切片。
- 官方曲包封面 / topbar 资源库。

## 文档更新规则

每次版本收口后，同步更新 `README.md`、`AGENT.md` 和本文档，并明确区分“已经实现”“正在开发”“尚待人工验收”“已取消”和“远期候选”。
