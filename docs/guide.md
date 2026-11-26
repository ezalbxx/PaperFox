# 纸狐使用指南

## Windows 桌面版

1. [下载 Windows x64 便携版](https://github.com/ezalbxx/PaperFox/releases/latest/download/PaperFox-Windows-x64.zip)，完整解压后运行 `PaperFox.exe`。请保留同目录的 `_internal`、`tectonic`、`fonts` 和图标文件。
2. 首次打开时，在「模型设置」选择供应商和支持工具调用的模型，填写自己的 API Key，再点击「验证并保存」。
3. 新建实验报告，选择实验材料目录和指导书。可在上传区添加模板或补充文件，再点击「开始制作」。
4. 在制作进度中确认导入目录，完成后在工作台阅读、改稿或下载 PDF。

桌面版使用系统的 [Microsoft Edge WebView2 Evergreen Runtime](https://developer.microsoft.com/microsoft-edge/webview2/#download-section)。如果启动提示组件缺失，安装运行时后重新打开纸狐。便携包已含 Python 运行库和 LaTeX 编译器。首次 LaTeX 排版可能需要下载宏包，编译失败时纸狐会尝试备用排版。

升级前请先退出纸狐。如果仍在制作报告，先暂停并等待进度保存。升级后沿用现有本机报告库。

## 指导书和材料

- 指导书支持可提取文本的 PDF、DOCX、PPTX、截图、照片和 UTF-8 文本。多张截图可逐张设为「实验指导书」，图片文字通过本机 [RapidOCR](https://github.com/RapidAI/RapidOCR) 提取。
- 旧版 DOC、PPT 分别需要本机 Microsoft Word 和 PowerPoint。扫描 PDF 可先做 OCR，也可上传页面截图。选错指导书时，可以在制作进度里更换。
- 结果材料可以包含代码、Notebook、Excel、CSV、日志和图片。纸狐会利用已有的记录写报告。有数据缺测时，会在「实验与数据反馈」列出缺项和影响。

## 模型和数据

- 内置 DeepSeek、千问、OpenAI、Claude、Gemini 和 Ollama 配置。自定义 API 支持 OpenAI Chat Completions、OpenAI Responses、Anthropic Messages 和 Gemini generateContent。
- Ollama 可用「无需密钥」。不支持流式输出的兼容接口可打开「非流式兼容模式」。连接失败时，核对地址、协议、模型 ID、鉴权和代理设置。模型验证会发送合成测试请求，可能产生少量用量。
- 报告保存在 `%LOCALAPPDATA%\PaperFox\Reports`，模型密钥由 Windows 加密保存。生成报告所需的材料会交给所选模型服务，云端服务按实际用量计费。

## 从源码运行

Windows 上请使用 [Python 3.11 或 3.12 x64](https://www.python.org/downloads/windows/)。克隆仓库或从 Release 下载源码，双击 `scripts\start_paperfox_source.cmd` 即可启动浏览器开发入口。需要从源码启动独立窗口时，在该环境安装 `.[paperfox,desktop]` 后，以 `PYTHONPATH=src` 运行 `python scripts/paperfox_windows.py --desktop`。

打包流程见 [Windows 构建脚本](../scripts/build_paperfox_windows.py)，随包第三方组件见 [组件与来源](paperfox-release-components.md)。未安装 Tectonic 的源码环境使用备用排版。
