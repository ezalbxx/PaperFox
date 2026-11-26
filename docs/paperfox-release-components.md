# 组件与来源

- 纸狐应用的对应源代码在 `PaperFox-source.zip`。
- Python 依赖版本见 `runtime-requirements.txt`，随包的上游许可证见 `third-party-licenses`。各 Python 包的源码项目链接可从 [PyPI](https://pypi.org/) 对应版本页面查看。
- PDF 组件 [PyMuPDF 源码](https://github.com/pymupdf/PyMuPDF) 使用 MuPDF。 [MuPDF 源码](https://mupdf.com/releases/)
- LaTeX 组件来自 [Tectonic 0.17.0](https://github.com/tectonic-typesetting/tectonic/releases/tag/tectonic%400.17.0)，许可证见 `tectonic/LICENSE`。
- 备用中文字体来自 [Noto CJK](https://github.com/notofonts/noto-cjk)，许可证见 `fonts/OFL.txt`。系统字体由本机提供。
- 运行环境使用 [CPython](https://www.python.org/downloads/) 和 [PyInstaller](https://github.com/pyinstaller/pyinstaller)。
- 桌面窗口由 [pywebview](https://pywebview.flowrl.com/) 创建，使用 Windows 上安装的 [Microsoft WebView2 Runtime](https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution)。
