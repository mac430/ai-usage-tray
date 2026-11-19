# AI Usage Tray

在 Windows 工作列通知區顯示 **Gemini**（網頁版／App 聊天方案）與 **Codex**（ChatGPT 方案）的用量，一個平台一個圖示。
搭配 [usage-monitor-for-claude](https://github.com/jens-duttke/usage-monitor-for-claude) 顯示 Claude，就能三家並排。

> ⚠️ 非官方工具，與 Google、OpenAI、Anthropic 無關。讀取方式都不是官方公開 API，對方改版可能隨時失效。

## 功能

- 圖示：大數字＝目前用量（預設顯示「已使用 %」，可切換成「剩餘 %」）；上條＝短時窗、下條＝每週（Codex Go 方案只有每月一條）。顏色依剩餘量綠／黃／紅。
- 滑鼠移上去看詳細與重設時間；右鍵選單：立即更新、重新登入、顯示模式、開機自動啟動、結束。
- 每 10 分鐘讀一次，失敗自動退避（最長 30 分鐘）；暫時讀不到時沿用最近 2 小時內的資料並標示為過期。
- 已用 80%、95% 時各發一次 Windows 通知；額度重設後重新計算。
- 設定精靈：第一次執行自動開啟，引導登入 Gemini、檢查 Codex／Claude 登入、建立捷徑與開機啟動。

## 運作方式

| 平台 | 資料來源 |
| --- | --- |
| Gemini | 用獨立的 Chrome 設定檔（`%LOCALAPPDATA%\ai-usage-tray\gemini-profile`）登入一次 Google，之後以無頭 Chrome 讀取 `gemini.google.com/usage` 頁面文字並解析。 |
| Codex | 讀本機 Codex 的登入檔 `%USERPROFILE%\.codex\auth.json`（只讀、不刷新不改寫），查詢 `chatgpt.com/backend-api/wham/usage`。 |
| Claude | 不在本專案內，請另外安裝 usage-monitor-for-claude。 |

- Gemini 專用設定檔裡存有 Google 登入狀態，請像密碼一樣保管；刪除該資料夾＝登出。
- Gemini 頁面解析目前只在**繁體中文**介面實測過，英文標籤為推測。
- 自動讀取網頁可能不符合服務條款的預期用途，請自行評估；本工具只讀你自己的帳號，頻率很低。

## 需求

- Windows 10／11、Google Chrome
- 從原始碼執行：Python 3.11+
- Codex：用 ChatGPT 帳號登入過 Codex（CLI、VS Code 擴充或桌面版皆可）

## 使用方式

### 打包成 exe（建議）

在有 Python 的電腦上執行一次：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File build.ps1
```

會產生 `dist\AIUsageTray\`（資料夾版 exe），安裝到 `%LOCALAPPDATA%\Programs\AIUsageTray-exe`，並在桌面輸出 `AIUsageTray-win.zip`。
其他電腦解壓到固定位置後雙擊 `AIUsageTray.exe` 即可，不需要 Python；第一次會自動開設定精靈。

### 從原始碼執行

```powershell
python -m pip install -r requirements.txt
python -m aiusage wizard          # 設定精靈
python -m aiusage tray all        # 啟動全部圖示
```

其他指令（除錯用）：

```powershell
python -m aiusage gemini once     # 讀一次 Gemini 並印出結果
python -m aiusage codex once      # 讀一次 Codex 並印出結果（不含 token）
python -m aiusage tray gemini     # 只開 Gemini 圖示
python -m unittest discover -s tests -t .
```

記錄檔與設定：`%LOCALAPPDATA%\ai-usage-tray\`

## 授權

MIT，見 [LICENSE](LICENSE)。第三方套件與設計參考見 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
