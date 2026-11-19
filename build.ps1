$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)
$app = "$env:LOCALAPPDATA\Programs\AIUsageTray-exe"

Write-Host "[1/5] 結束正在跑的圖示"
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*run_tray.py*" -or $_.CommandLine -like "*aiusage*tray*" -or $_.ExecutablePath -like "*AIUsageTray*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1

Write-Host "[2/5] 安裝打包工具與套件"
python -m pip install -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip 安裝失敗" }

Write-Host "[3/5] 打包（需要幾分鐘）"
python -m PyInstaller --noconfirm --clean --noconsole --name AIUsageTray --collect-all playwright --collect-submodules aiusage --hidden-import pystray._win32 run_tray.py
if ($LASTEXITCODE -ne 0) { throw "打包失敗" }

Write-Host "[4/5] 安裝到 $app 並壓縮一份給其他電腦用"
New-Item -ItemType Directory -Force $app | Out-Null
robocopy "dist\AIUsageTray" $app /MIR /NFL /NDL /NJH /NJS | Out-Null
$zipOut = Join-Path ([Environment]::GetFolderPath('Desktop')) "AIUsageTray-win.zip"
Compress-Archive -Path "dist\AIUsageTray" -DestinationPath $zipOut -Force

Write-Host "[5/5] 開啟設定精靈"
Start-Process "$app\AIUsageTray.exe" -ArgumentList "wizard"
Write-Host "完成。給筆電用的壓縮檔在桌面：$zipOut"
