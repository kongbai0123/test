testing git & learning python project
主選單能跑（1/2/3/4）
選 1 能「顯示目前習慣」並「新增一個習慣」且存到檔案

1.設計概念
你在做的是一個小系統，所以最重要的是「資料能保存」。
先把流程串起來，之後再把今日打卡與統計補上。

2.在專案資料夾內建立.json
["運動", "讀書"]

3.def load_habits():
。open(..., encoding="utf-8")：中文習慣名稱才不會亂碼。
。with open(...) as f：好習慣，讀完會自動關檔（避免檔案被鎖住或忘記關）。
。json.load(f)：把 JSON 檔案內容轉成 Python 物件（這裡就是 list）。

4.def save_habits(habits):
。"w"：寫入模式（會覆蓋舊內容）。因為我們每次保存都存最新整份清單。
。ensure_ascii=False：不然中文會變成 \u904b\u52d5 這種形式，難讀。
。indent=2：漂亮排版，方便你打開檔案人工檢查。

5.def habit_menu():
。habits = load_habits()：習慣清單要以檔案為主（持久化來源）。
。enumerate(..., start=1)：印出 1,2,3 編號比較直覺。
。.strip()：去掉前後空白，避免你輸入 "運動 " 造成重複的髒資料。
。if new_habit in habits：避免重複，否則後面統計會「同一習慣被當成兩個」。






