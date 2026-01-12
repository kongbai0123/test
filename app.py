#每日習慣打卡與統計 包含三件事：
# 資料：習慣清單、每天打卡紀錄
# 流程：新增習慣 → 每天打卡 → 查統計
# 保存：關掉程式後資料不能消失（存檔）

import json
from pathlib import Path # Path 讓你用跨平台且更安全的方式處理路徑

DATA_DIR = Path(__file__).parent / "data"
HABITS_FILE = DATA_DIR / "habits.json"


def main():
    ensure_data_files()
    while True:
        print("1) 設定習慣")
        print("2) 今日打卡(未完成)")
        print("3) 看統計(未完成)")
        print("4) 離開")

        choice = input("請輸入選項:")

        if choice == '1':
            habit_menu()
        elif choice == '2':
            print("今日打卡：尚未實作")
        elif choice == '3':
            print("尚未實作")
        elif choice == '4':
            print("離開")
            break
        else:
            print("輸入錯誤")
# 先寫 load_habits（最基本版本）
def load_habits():
    with open(HABITS_FILE, "r", encoding="utf-8") as f:
        habits = json.load(f)
    return habits
# 再寫 save_habits（最基本版本）
def save_habits(habits):
    with open(HABITS_FILE, "w", encoding="utf-8") as f:
        json.dump(habits, f, ensure_ascii=False, indent=2)
# 做「習慣管理」功能
def habit_menu():
    while True:
        habits = load_habits()

        print("\n=== 習慣管理 ===")
        if len(habits) == 0:
            print("目前沒有習慣。")
        else:
            print("目前習慣清單：")
            for i, h in enumerate(habits, start=1):
                print(f"{i}. {h}")

        print("\n1) 新增習慣")
        print("2) 返回主選單")
        sub = input("請輸入選項：").strip()

        if sub == "1":
            new_habit = input("請輸入『習慣名稱』（例如：運動、讀書）：").strip()

            if new_habit == "":
                print("空白名稱無效。")
                continue

            # 避免使用純數字（降低誤用）
            if new_habit.isdigit():
                print("請輸入文字名稱，不要輸入數字編號。")
                continue

            if new_habit in habits:
                print("此習慣已存在。")
                continue

            habits.append(new_habit)
            save_habits(habits)
            print("新增完成。")

        elif sub == "2":
            break
        else:
            print("輸入錯誤，請輸入 1 或 2。")

# 加入初始化函式
def ensure_data_files():
    #沒有 data/ 就建立
    DATA_DIR.mkdir(exist_ok=True)
    if not HABITS_FILE.exists():
        # 沒有 habits.json 就初始化成空清單 []
        HABITS_FILE.write_text("[]", encoding="utf-8")

if __name__ == "__main__":
    main()

