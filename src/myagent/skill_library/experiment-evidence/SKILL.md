---
name: experiment-evidence
description: 本项目原创实验留痕技能，保存当前真实对话JSONL前缀与提交JSON，返回工具调用及结果的实际行号。
---
# 实验留痕

作者：本项目，2026-10-26。未移植第三方Agent工具或技能。

调用 `run_skill`，skill=`experiment-evidence`、operation=`snapshot`，inputs：

- `output_dir`：工作区内证据目录，例如 `evidence/report-input`。

保存本次调用前的真实JSONL前缀和可提交JSON，返回trace/export路径、行数、最近8组实际配对的调用/结果行号与输出摘要；完整配对索引为evidence-index.json。返回行号由原事件直接计算，可以直接引用。结合已经看过的输出立即写报告，不要把整个JSONL重新读一遍；仅在具体结论缺证据时读取相应小段。运行中快照并非完整run，不能谎称包含未来动作或run_end。本次snapshot的结果和之后生成PDF的动作，要在任务结束后通过界面导出留存。复用相同output_dir会更新快照；报告引用后保持该目录不动，后续使用新目录。

这项技能只导出当前对话的公开事件，不能浏览其它会话、密钥或内部推理。
