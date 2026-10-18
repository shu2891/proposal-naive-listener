# proposal-naive-listener｜提案陌生聽眾

逐頁或逐段記錄第一次接觸提案的聽眾「目前以為這是什麼」，找出可能的理解缺口。主要使用環境是 Codex，其他代理環境尚未驗證。

它會保留當時的理解、猜測與疑問；後頁解開問題時新增修復紀錄，不把前面的猜測改成早就理解。一般生活常識可以形成推論，未揭露的專案設定不能當成事實。

## 安裝到 Codex

下載本 repo 的 ZIP，或使用 Git：

```text
git clone https://github.com/shu2891/proposal-naive-listener.git
```

解壓縮分享包，將完整的 `proposal-naive-listener` 資料夾放入使用者的 `.agents/skills/`，不要只複製 `SKILL.md`：

```text
~/.agents/skills/proposal-naive-listener/
├── SKILL.md
├── agents/openai.yaml
├── references/protocol.md
├── scripts/reveal.py
└── ...
```

Windows 的對應位置是 `%USERPROFILE%\.agents\skills\proposal-naive-listener\`；macOS/Linux 是 `~/.agents/skills/proposal-naive-listener/`。也可以放在特定專案的 `.agents/skills/proposal-naive-listener/`。上述位置依 [OpenAI 官方 skills 文件](https://learn.chatgpt.com/docs/build-skills)；若你的環境已有其他 skills 路徑，請讓 Codex 確認該環境實際使用的目錄。

Codex 會偵測 skill；若未出現，重新啟動 Codex。請只安裝一份，避免同名 skill 重複出現。[官方說明](https://learn.chatgpt.com/docs/build-skills)

## 第一次使用

附上提案，在 Codex 輸入：

> 請使用 $proposal-naive-listener，逐頁測試這份提案。受眾是沒有專案背景的一般成人，先聽完再問。請保留每頁當下的理解和猜測，最後指出可能的理解斷點與最少需要補的說明。

也可以逐段貼入文字。新版本應重新測試；若指定「繼續同一次測試」，則保留該場次的已知內容。

最好用新的對話或由 Codex 啟動無歷史的獨立聽眾。若模型已看過全文或參與過專案討論，skill 必須標示資訊污染，不能把它稱為首次接觸盲測。

預設先聽完再問。需要互動排練時，改成「核心理解卡住時先問我」；實際澄清回答會另存，保留回答前的理解紀錄。

## 檔案與依賴

- 逐段文字：可以直接測試，不需要 PDF 渲染套件。
- PDF：按頁渲染成影像，避免把隱藏文字層與註解當作觀眾所見。
- PPT/PPTX：需要環境可用的簡報工具先轉成 PDF 或逐頁圖片；本包不自帶 PPT 轉檔器。
- 現場講解：提供確定會說出口的逐頁講稿；講者備註不自動算作已聽到。

揭露腳本需要 Python 3.10+。若環境已可渲染 PDF，沿用現有套件即可；否則可在你選定的 Python 環境安裝：

```text
python -m pip install -r requirements-pdf.txt
```

`requirements-pdf.txt` 提供 PDFium 與 Pillow。腳本也支援既有的 PyMuPDF。安裝套件不會替你配置模型；請在已有可用模型的 Codex 環境執行這個 skill。

## 看一個例子

`examples/demo.json` 是四段合成文字，依序呈現資訊不足、角色說明、角色矛盾與後續更正。請讓聽眾逐段接收，不先讀完整份。

`examples/demo-report.md` 與 `examples/demo-timeline.md` 是已完成的一次 AI 模擬結果，逐段原始紀錄保存在 `examples/snapshots/`；**測試前不要把報告、時間軸或原始紀錄交給聽眾**，以免提供答案。

工具的命令、原始紀錄格式與互動模式規則見 [references/protocol.md](references/protocol.md)。只測逐段文字時，不必先學會這些命令，可以讓 Codex 依 skill 執行。

## 輸出

Codex 會在你的工作區建立測試 session，保留：

- `snapshots/`：逐頁原始紀錄。
- `mental-model.md`：截至目前的理解與依據。
- `assumptions.md`、`questions.md`：猜測與疑問歷史。
- `comprehension-timeline.md`：理解、受阻、修正與修復的時間軸。
- `report.md`：測試條件、主要缺口及最少編輯建議。

沒有正確解讀或後續證據時，只能說「有誤解風險」，不能武斷地判定聽眾在哪頁開始理解錯誤。

## 已做的驗證與限制

五項工具行為測試曾在 PyMuPDF 和 PDFium 環境通過；另完成一次四段文字的獨立聽眾模擬。這不代表對真實人類的理解已有預測效度，也不代表 PPT 轉檔、動畫或所有代理環境均已驗證。

逐頁閘門控制操作順序和引用範圍，不是作業系統沙箱；語意真實性與代理是否越界仍需檢查。AI 仍有預訓練知識，實際讀者的背景也不同。

要驗證真人效果，請找沒接觸過提案、符合目標受眾的人逐頁復述，與 AI 的可能斷點比對。

## 方法參考

設計參考 [naive-user](https://github.com/TechGardenCode/naive-user) 的 source-blind 與 mental model 記錄思路，也參照 [AGENT-CQ-Data](https://github.com/Clemenciah/AGENT-CQ-Data) 與 [Ask or Assume?](https://github.com/nedwards99/ask-or-assume) 的澄清問題方向。本包的 skill 和腳本是獨立編寫，未複製這些專案的程式或 prompt。

## 執行工具測試

安裝 PDF 依賴後，在 repo 目錄執行：

```text
python scripts/test_reveal.py -v
```

## 授權

本專案採用 [MIT License](LICENSE)。
