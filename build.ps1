$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)
$app = "$env:LOCALAPPDATA\Programs\AIUsageTray-exe"

Write-Host "[1/6] 結束正在跑的圖示"
# 用名稱關（以系統管理員權限開的程序，一般權限讀不到路徑，用路徑比對會漏掉）
Get-Process -Name "AIUsageTray*" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*run_tray.py*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1
if (Get-Process -Name "AIUsageTray*" -ErrorAction SilentlyContinue) {
    throw "有 AIUsageTray 程式關不掉（可能是用系統管理員權限開的）。請用「以系統管理員身分執行」的 PowerShell 執行：Stop-Process -Name AIUsageTray* -Force，再重新執行打包"
}

Write-Host "[2/6] 建立乾淨的虛擬環境（只裝需要的套件，避免把無關的大型套件打包進去）"
if (Test-Path .build-venv) { Remove-Item .build-venv -Recurse -Force }
python -m venv .build-venv
$py = ".\.build-venv\Scripts\python.exe"
& $py -m pip install --upgrade pip | Out-Null
& $py -m pip install -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip 安裝失敗" }

Write-Host "[3/6] 打包（需要幾分鐘）"
& powershell -NoProfile -ExecutionPolicy Bypass -File tools\package.ps1 -Python (Resolve-Path $py)
if ($LASTEXITCODE -ne 0) { throw "打包失敗" }

Write-Host "[4/6] 安裝到 $app"
New-Item -ItemType Directory -Force $app | Out-Null
robocopy "dist\AIUsageTray" $app /MIR /R:3 /W:1 /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "複製到安裝資料夾失敗（有檔案被其他程式使用中）。請關掉 AIUsageTray 相關程式後重新執行" }

Write-Host "[5/6] 壓縮一份給其他電腦用"
$zipOut = Join-Path ([Environment]::GetFolderPath('Desktop')) "AIUsageTray-win.zip"
Compress-Archive -Path "dist\AIUsageTray" -DestinationPath $zipOut -Force
$size = (Get-ChildItem "dist\AIUsageTray" -Recurse | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("資料夾大小：{0:N1} MB，壓縮檔：{1:N1} MB" -f $size, ((Get-Item $zipOut).Length / 1MB))

Write-Host "[6/6] 啟動圖示"
Start-Process "$app\AIUsageTray.exe" -ArgumentList "autostart"
Write-Host "完成。給筆電用的壓縮檔在桌面：$zipOut"
