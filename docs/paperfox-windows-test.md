# 纸狐 Windows 测试版

1. 在 Windows 10 / 11 的 x64 电脑上完整解压 ZIP。
2. 打开解压目录，双击 **PaperFox.exe**。工作台会在独立的桌面窗口打开。再次双击会唤起已有窗口。请让 EXE 和同目录的 `_internal`、`tectonic`、`fonts` 一起保留。
3. 首次使用时，在「模型设置」选择供应商和模型，输入自己的 API Key，然后点击「验证并保存」。同一 Windows 账户已配置过纸狐时，可以直接使用已有设置。
4. 点击「新建实验报告」，选择存放已有代码、结果、日志或图表的实验材料目录，再选择指导书。指导书可以放在材料目录内，也可以单独存放。自带报告模板时，可以上传并将用途选为「报告模板」。
5. 点击「开始制作」。可在「制作进度」里查看状态，完成后在工作台下载 PDF。

写作所需的材料会提交给所选模型，联网调用由对应服务商计费。验证模型连接可能产生少量用量。

模型连接失败时，可在模型设置里核对地址、鉴权和代理。若启动时提示缺少桌面渲染组件，请安装 Microsoft 的 [WebView2 Evergreen Runtime](https://developer.microsoft.com/microsoft-edge/webview2/#download-section) 后重开。

PDF 和 DOCX 指导书可直接读取。扫描件需先做 OCR。旧版二进制 DOC 由本机 Microsoft Word 读取，也可先转换成 DOCX 或可提取文字的 PDF。

程序已带 Python 运行库、LaTeX 编译器和备用中文字体。第一次导出 LaTeX 可能需要下载所用的宏包。编译无法完成时会记录原因，并在可用时以备用渲染器交付 PDF。

报告保存在本机 `%LOCALAPPDATA%\PaperFox\Reports`，API Key 由 Windows 加密保存，选中的材料会复制进独立报告项目，原文件保持原样。启动日志位于 `%LOCALAPPDATA%\PaperFox\startup.log`。

关闭桌面窗口或从工作台左下角选择「退出程序」，都会关闭程序。有报告正在处理时，先暂停并等待进度保存。
