# 共用的打包步驟（本機 build.ps1 與 GitHub 自動打包都用這支）
# 用法：powershell -File tools\package.ps1 -Python <python.exe 路徑>
# 產出：dist\AIUsageTray\（資料夾版 exe）
param([Parameter(Mandatory = $true)][string]$Python)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))

& $Python -m PyInstaller --noconfirm --clean --noconsole --name AIUsageTray `
    --collect-submodules aiusage --hidden-import pystray._win32 `
    --exclude-module numpy --exclude-module PIL.ImageQt --exclude-module PIL.ImageTk `
    run_tray.py
if ($LASTEXITCODE -ne 0) { throw "打包失敗" }

# 每個圖示一個專屬 exe（同一份程式的複本，共用 _internal），Windows 才會把兩個圖示分開記
Copy-Item "dist\AIUsageTray\AIUsageTray.exe" "dist\AIUsageTray\AIUsageTray-Gemini.exe" -Force
Copy-Item "dist\AIUsageTray\AIUsageTray.exe" "dist\AIUsageTray\AIUsageTray-Codex.exe" -Force
Copy-Item LICENSE "dist\AIUsageTray\LICENSE.txt" -Force
Copy-Item THIRD_PARTY_NOTICES.md "dist\AIUsageTray\THIRD_PARTY_NOTICES.md" -Force
