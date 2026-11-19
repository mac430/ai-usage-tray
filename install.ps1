$ErrorActionPreference = "Stop"
$src = Split-Path -Parent $MyInvocation.MyCommand.Path
$dst = "$env:LOCALAPPDATA\Programs\AIUsageTray"
Write-Host "安裝位置：$dst"

# 1. 結束正在跑的舊圖示
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*run_tray.py*" -or $_.CommandLine -like "*aiusage*tray*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1

# 2. 安裝 Python 套件
python -m pip install -r "$src\requirements.txt"
if ($LASTEXITCODE -ne 0) { throw "pip 安裝失敗" }

# 3. 複製程式到固定位置
if ($src -ne $dst) {
    New-Item -ItemType Directory -Force $dst | Out-Null
    robocopy $src $dst /MIR /XD __pycache__ tests /NFL /NDL /NJH /NJS | Out-Null
}

# 4. 桌面捷徑 + 開機自動啟動（單一項目）
$py = python -c "import sys;print(sys.executable)"
$pyw = Join-Path (Split-Path $py) "pythonw.exe"
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut("$([Environment]::GetFolderPath('Desktop'))\AI 用量.lnk")
$lnk.TargetPath = $pyw
$lnk.Arguments = "`"$dst\run_tray.py`" all"
$lnk.WorkingDirectory = $dst
$lnk.Save()
$run = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
foreach ($old in "ai-usage-tray-gemini", "ai-usage-tray-codex") { Remove-ItemProperty -Path $run -Name $old -ErrorAction SilentlyContinue }
Set-ItemProperty -Path $run -Name "ai-usage-tray-all" -Value "`"$pyw`" `"$dst\run_tray.py`" all"

# 5. 啟動
Start-Process $pyw -ArgumentList "`"$dst\run_tray.py`" all" -WorkingDirectory $dst
Write-Host "完成。桌面有「AI 用量」捷徑；開機會自動啟動 Gemini 與 Codex 圖示。"
