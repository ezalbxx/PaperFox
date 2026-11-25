---
name: code-workspace
description: 本项目原创结构化代码工作技能：读写与精确编辑文件、执行已保存Python任务、保留退出码和输出；不提供shell命令接口。
---
# 代码工作

作者：本项目，2026-10-26；工具协议、调度与证据均自行实现。

使用 `run_skill`，skill=`code-workspace`：

- `read`，inputs：`path`；读取UTF-8源码。
- `write`，inputs：`path`、`content`；保存代码、数据、报告JSON等。
- `edit`，inputs：`path`、`old_text`、`new_text`；对现有唯一匹配片段精准替换，具体选项以返回错误为准。
- `run_python`，inputs：`path`（已保存.py）、`timeout_s`（前台≤30秒）、`background`（可选，长任务设true并给出总时限）。返回实际退出码/stdout及源码哈希，后台返回作业ID。只在trusted执行设置中运行。

不接受命令字符串、任意可执行文件/argv或内联代码执行。不得生成调用shell/cmd/PowerShell/bash的代码。Python任务用文件/数值/绘图等领域API；内置检查只处理常见直接进程启动，不是操作系统沙箱。需要新增领域能力时交由开发者新增明确技能，不能把命令接口伪装成技能。

先读已有文件再小范围修改；依照用户本轮范围运行必要验证，复用有效结果，完成后收口。后台用job_status/job_logs/cancel_job查询；不要反复花模型调用轮询。课程记录保留来源页码、源码、运行结果、JSONL工具配对和失败。标准库用于环境/文件/算法，第三方包依赖如实说明。
