$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)
$app = "$env:LOCALAPPDATA\Programs\AIUsageTray-exe"

Write-Host "[1/6] 結束正在跑的圖示"
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*run_tray.py*" -or $_.CommandLine -like "*aiusage*tray*" -or $_.ExecutablePath -like "*AIUsageTray*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1

Write-Host "[2/6] 建立乾淨的虛擬環境（只裝需要的套件，避免把無關的大型套件打包進去）"
if (Test-Path .build-venv) { Remove-Item .build-venv -Recurse -Force }
python -m venv .build-venv
$py = ".\.build-venv\Scripts\python.exe"
& $py -m pip install --upgrade pip | Out-Null
& $py -m pip install -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip 安裝失敗" }

Write-Host "[3/6] 打包（需要幾分鐘）"
& $py -m PyInstaller --noconfirm --clean --noconsole --name AIUsageTray `
    --collect-submodules aiusage --hidden-import pystray._win32 `
    --exclude-module numpy --exclude-module PIL.ImageQt --exclude-module PIL.ImageTk `
    run_tray.py
if ($LASTEXITCODE -ne 0) { throw "打包失敗" }
Copy-Item LICENSE "dist\AIUsageTray\LICENSE.txt" -Force
Copy-Item THIRD_PARTY_NOTICES.md "dist\AIUsageTray\THIRD_PARTY_NOTICES.md" -Force

Write-Host "[4/6] 安裝到 $app"
New-Item -ItemType Directory -Force $app | Out-Null
robocopy "dist\AIUsageTray" $app /MIR /NFL /NDL /NJH /NJS | Out-Null

Write-Host "[5/6] 壓縮一份給其他電腦用"
$zipOut = Join-Path ([Environment]::GetFolderPath('Desktop')) "AIUsageTray-win.zip"
Compress-Archive -Path "dist\AIUsageTray" -DestinationPath $zipOut -Force
$size = (Get-ChildItem "dist\AIUsageTray" -Recurse | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("資料夾大小：{0:N1} MB，壓縮檔：{1:N1} MB" -f $size, ((Get-Item $zipOut).Length / 1MB))

Write-Host "[6/6] 啟動圖示"
Start-Process "$app\AIUsageTray.exe" -ArgumentList "all"
Write-Host "完成。給筆電用的壓縮檔在桌面：$zipOut"
