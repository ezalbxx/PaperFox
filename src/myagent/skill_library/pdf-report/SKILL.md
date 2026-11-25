---
name: pdf-report
description: 本项目原创中文实验报告排版技能，把结构化章节、实测结果和来源证据生成PDF与哈希清单。
---
# 实验报告生成

作者：本项目，2026-10-26。未移植开源Agent工具或现成技能。
底层排版库：ReportLab；章节组织、中文样式、表格分页和证据清单为本项目实现。

调用 `run_skill`，skill=`pdf-report`、operation=`build`、inputs：

- `document`：已保存的UTF-8 JSON路径。
- `output`：PDF相对路径。

JSON：`title`、`subtitle`（可选）、`student_id`、`sections`、`sources`。
每个section含`heading`和`blocks`。block可以是段落字符串；也可以是：

- `{"type":"table","headers":["项目","结果"],"rows":[["样例","实测结果"]]}`
- `{"type":"list","items":["第一条","第二条"]}`
- `{"type":"code","text":"原始输出片段"}`

sources每项含`path`（必须存在）、`locator`（原页码/轨迹行号）。生成PDF及同名manifest.json，保留来源/报告哈希。生成成功不代表实验通过。

课程报告按指导书八节组织。先读要求，再执行实验，结果来自真实技能调用/产物；失败、跳过、未完成分别说明。不要把建议和计划写成已运行。若只有部分验收，就交付明确标注范围的阶段报告。生成后用pdf-reader读取核对中文与章节，render关键页并交由可视界面检查。
