# AI 写作插件

## 场景描述

帮助用户撰写结构化的长篇文章或技术报告。工作流分六步：

1. **build_context** — 解析写作意图、目标读者、核心子主题、风格与事实共识
2. **generate_outline** — 基于上下文生成结构化大纲
3. **plan_sections** — 根据大纲为每章生成写作指令
4. **generate_draft** — 按章节指令串行撰写完整初稿
5. **review_document** — 多维度审阅初稿，给出评分与修改建议
6. **finalize_report** — 根据审阅意见修订，产出最终成稿

每个步骤支持整体重跑：用户对某一步结果不满意时，可重新触发该步骤。

## 用户意图识别

### 冷启动（无活跃会话）

- 用户提到「写一篇报告」「起草一份文章」「写一篇综述」「写一篇关于 X 的介绍」等
  长文写作请求 → 调用 `trigger_writer_plugin(user_input=<用户原始需求>)`

  `user_input` 应当是一个具体的写作目标陈述，包含主题、体裁与任何篇幅或风格要求。

### 有活跃会话时

| 用户意图 | 推荐步骤 | 工具调用 |
|---|---|---|
| 想重新解析写作意图 | build_context | `advance_step(step_id='build_context', user_input=<说明>)` |
| 对大纲不满意，想重新生成 | generate_outline | `advance_step(step_id='generate_outline', user_input=<说明>)` |
| 想重新规划章节指令 | plan_sections | `advance_step(step_id='plan_sections', user_input=<说明>)` |
| 想重写初稿 | generate_draft | `advance_step(step_id='generate_draft', user_input=<说明>)` |
| 想重新审阅 | review_document | `advance_step(step_id='review_document', user_input=<说明>)` |
| 想重新产出终稿 | finalize_report | `advance_step(step_id='finalize_report', user_input=<说明>)` |
| 对最终结果满意 | （无需操作，DriverAgent 自动判 DONE） | — |

当用户或 DriverAgent 指出问题源于某个前序步骤时，使用 `advance_step` 并传入该前序步骤的 `step_id` 即可回退重做。可用的前序步骤由 `advance_step` 工具的 Rewind 列表动态给出，无需在此枚举。

## 注意

- 冷启动走 `trigger_writer_plugin`，把用户原始需求作为 `user_input` 传入。
- 工具返回后，对用户简短说明当前正在进行的步骤，例如：
  - 冷启动：「正在解析您的写作需求，请稍候……」
  - 重新生成大纲：「正在重新生成大纲……」
- 涉及具体写作内容（章节草稿、最终成稿等）由 subagent 协作的工具完成，主 Agent 不必再复述正文。
