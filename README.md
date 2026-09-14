# 額度恢復接續外掛

Codex 桌面版個人外掛：透過同任務排程，在額度可用時嘗試接續未完成的工作。

## 下載與安裝

從 [Releases](https://github.com/ilzfor/quota-resume/releases) 下載 `quota-resume-0.1.0.zip`，完整解壓後，將其中的 `quota-resume` 資料夾交給 Codex，輸入：

> 請將這個 quota-resume 資料夾安裝成我的 Codex 個人外掛。請使用本機外掛安裝流程，保留既有市集與外掛設定，驗證安裝成功；先不要替任何任務啟用自動接續。

也可以下載或 clone 本儲存庫，使用其中的 `quota-resume/` 資料夾。詳細步驟見 [安裝說明](quota-resume/安裝說明.md)。

## 使用

在要接續工作的任務中輸入：

> 使用 $quota-resume，替這個任務啟用額度恢復後自動接續，完成原本工作後停止。

預設每 5 分鐘透過原生排程嘗試接續原任務。請在額度用完前啟用，並讓電腦開機、連線及 Codex App 運行。若既有任務未辨識到新技能，使用外掛頁面選取／附加外掛；新任務會載入已安裝技能。

這個版本沒有常駐背景服務，也不是零 token 監控器。原生排程在真正耗盡額度時的重試／暫停行為尚未驗證，因此不保證恢復的瞬間或特定分鐘內必定接續。安裝後仍需在要執行的任務啟用排程。

- [完整使用說明](quota-resume/README.md)
- [外掛技能](quota-resume/skills/quota-resume/SKILL.md)
- [驗證結果](驗證結果.md)

## 開發與打包

開發驗證：`python -m unittest discover -s tests -v`。

使用 Python 3 執行 `python package_plugin.py`，產生 `dist/quota-resume-0.1.0.zip`。測試與打包只使用 Python 標準函式庫。若修改此外掛，請重新打包並依 Codex 本機外掛的更新流程重裝。

停止方式：在原任務輸入「使用 $quota-resume 停止這個任務的自動接續」，或從 App 排程管理頁面停用。卸載外掛前也請先停用已建立的排程。
