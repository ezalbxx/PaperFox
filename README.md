# 纸狐 PaperFox

**把实验材料整理成一份可以阅读、修改和导出的实验报告。**

[项目主页](https://ezalbxx.github.io/PaperFox/) · [Windows 下载](https://github.com/ezalbxx/PaperFox/releases/latest) · [反馈问题](https://github.com/ezalbxx/PaperFox/issues)

纸狐从实验指导书、已有代码、结果和图表中梳理实验过程，规划章节，生成报告正文，并导出 PDF。你可以在工作台查看制作进度、阅读报告和修改选中的段落。

## 在 Windows 上运行

1. 安装 [Python 3.11 或 3.12 的 Windows x64 版本](https://www.python.org/downloads/windows/)，安装时保留 Python Launcher。下载并解压最新版本的源码 ZIP。
2. 双击 **scripts\start_paperfox_source.cmd**。首次启动会安装 Python 依赖，完成后浏览器会打开本机工作台。
3. 打开「模型设置」，选择供应商，填写模型 ID 和对应的 API Key，再点击「验证并保存」。也可以选择「自定义 API」，填入自己的接口地址。
4. 新建实验报告，选择实验材料文件夹和指导书。有单独的报告模板时，可以再上传模板。点击「开始制作」，完成后下载 PDF。

「制作进度」会显示本报告实际导入的材料目录。纸狐会自行读取其中的代码、环境记录和运行结果。缺少的实测结果按缺项处理，继续撰写有依据的内容。

升级或删除程序前，点击工作台左下角的电源图标，选择「退出程序」。如果有报告正在制作，先暂停并等待进度保存。升级后，工作台会打开原有的本机报告库。

「选择实验指导书」可浏览所有文件。常用格式包括 PDF、Word、PowerPoint、截图或照片，以及 UTF-8 纯文本。多张截图可拖入上传区，逐张将用途设为「实验指导书」。图片文字在本机通过 [RapidOCR](https://github.com/RapidAI/RapidOCR) 提取，写报告时识别出的正文按普通材料处理。

PPTX 可直接读取，包括幻灯片内嵌的常见图片。旧版 DOC、PPT 分别需要本机安装 Microsoft Word、PowerPoint。纯扫描 PDF 可先做 OCR，也可将页面截图选为指导书。文件读取失败时，可在原报告的制作进度页点击「更换指导书并继续」。

安装 [Tectonic](https://tectonic-typesetting.github.io/) 并加入 PATH 后，可使用 LaTeX 排版。未安装时，程序使用内置 PDF 排版。

## 数据与 API

工作台运行在本机，源文件保持原样，报告保存在 `%LOCALAPPDATA%\PaperFox\Reports`。API Key 由 Windows 加密保存。写作所需的材料会提交给所选模型，费用由对应服务商计收。纸狐记录用量，有模型计价信息时也会显示费用估算。

内置 DeepSeek、千问、OpenAI、Claude、Gemini 和 Ollama 配置。自定义地址支持 OpenAI Chat Completions、OpenAI Responses、Anthropic Messages 和 Gemini generateContent。用于写报告的模型需要支持工具调用。验证会发送一条合成测试请求，可能产生少量用量。仅接受私有协议或云签名鉴权的服务需要兼容网关。

本机 Ollama 可选择「无需密钥」，填写已安装且支持工具调用的模型 ID。兼容接口不支持流式输出时，可在高级选项打开「使用非流式兼容模式」。连接失败时，可核对地址、协议、模型 ID 和鉴权方式，或切换系统代理与直连。

觉得好用，欢迎在 [GitHub 仓库](https://github.com/ezalbxx/PaperFox) 点个 Star。
