# Third-party notices

本專案原始碼不含第三方程式碼。執行時（與打包後的 exe）會使用下列套件，各自依其授權條款：

| 套件 | 授權 | 網址 |
| --- | --- | --- |
| websocket-client | Apache-2.0 | https://github.com/websocket-client/websocket-client |
| pystray | LGPL-3.0 | https://github.com/moses-palmer/pystray |
| Pillow | MIT-CMU (HPND) | https://github.com/python-pillow/Pillow |
| Python / tkinter（Tcl/Tk） | PSF License / Tcl license | https://www.python.org/ |
| PyInstaller（僅打包時使用，bootloader 例外條款） | GPL-2.0 with bootloader exception | https://github.com/pyinstaller/pyinstaller |

pystray 以 LGPL-3.0 授權，打包版中以獨立模組形式包含，使用者可自行以修改後的版本替換（從原始碼執行即可）。

## 設計參考（未複製程式碼）

- [jens-duttke/usage-monitor-for-claude](https://github.com/jens-duttke/usage-monitor-for-claude)（MIT）：托盤圖示的「數字＋兩條用量條」版面概念。
- Codex 用量介面 `chatgpt.com/backend-api/wham/usage` 的欄位格式，參考開源專案 codex-lb、codex-switch 等公開的實作與文件。
