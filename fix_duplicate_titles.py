import pandas as pd
from google import genai
from google.genai.errors import APIError
import os
from dotenv import load_dotenv
import time
import re
import argparse

# ------------------- 載入 API Key -------------------
print("--- 載入設定與 API Key ---")
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ------------------- 初始化 Gemini Client -------------------
client = None
if not GEMINI_API_KEY:
    print("❌ 錯誤：找不到 GEMINI_API_KEY 環境變數。")
    print("請確保您的 .env 檔案中有 GEMINI_API_KEY。")
else:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        print("✓ Gemini Client 已初始化。")
    except Exception as e:
        print(f"❌ 初始化 Gemini Client 時發生錯誤: {e}")

# ------------------- 輔助函數 (Gemini 呼叫) -------------------


def generate_new_title_from_description(description):
    """
    使用 Gemini API 根據描述生成一個新標題。
    """
    prompt = f"""
    Based on the following description, generate a new, unique, and catchy English title under 60 characters.
    The title must be relevant but distinct from any previous titles.
    Only output the new title, nothing else.

    Description:
    "{description}"

    New Title:
    """

    if not client:
        # print("⚠️ 模擬模式：未呼叫 API (Client 初始化失敗)。") # 減少 log 雜訊
        time.sleep(0.5)
        return f"Simulated New Title for: {description[:30]}..."

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",  # 建議改用 2.0-flash 速度較快，或維持您的 2.5-pro
            contents=[prompt],
        )

        new_title = response.text.strip()
        new_title = re.sub(
            r"\[?title\]?\s*[:：]\s*", "", new_title, flags=re.IGNORECASE
        )
        if new_title.startswith('"') and new_title.endswith('"'):
            new_title = new_title[1:-1]

        if len(new_title) > 60:
            last_space = new_title[:60].rfind(" ")
            if last_space != -1:
                new_title = new_title[:last_space]
            else:
                new_title = new_title[:60]

        if not new_title:
            raise ValueError("API 返回了空標題")

        return new_title

    except APIError as e:
        print(f"❌ Gemini API 錯誤: {e}")
        return "ERROR: API Error"
    except Exception as e:
        print(f"❌ 未知錯誤: {e}")
        return "ERROR: Unknown Error"


# ------------------- 單一檔案處理函數 -------------------
def process_single_csv(input_path, output_path, args):
    """
    讀取一個 CSV，處理錯誤，並儲存。
    """
    filename = os.path.basename(input_path)
    print(f"\n📂 正在處理檔案: {filename}")

    try:
        # 嘗試讀取
        try:
            df = pd.read_csv(input_path, encoding="utf-8")
        except UnicodeDecodeError:
            print("  ⚠️ 'utf-8' 解碼失敗，嘗試 'latin1' ...")
            df = pd.read_csv(input_path, encoding="latin1")
    except Exception as e:
        print(f"  ❌ 讀取失敗: {e}")
        return

    # 檢查必要欄位
    required_cols = ["Title", "Description", "error"]
    if not all(col in df.columns for col in required_cols):
        print(f"  ⚠️ 跳過：缺少必要欄位 (Title, Description, error)。")
        return

    # 找出需要處理的 rows
    error_string = "Multiple rows with the same title"
    rows_to_process = df[df["error"].astype(str).str.contains(error_string, na=False)]

    if rows_to_process.empty:
        print(f"  ℹ️ 此檔案沒有發現 '{error_string}' 錯誤，跳過。")
        return

    print(f"  ℹ️ 找到 {len(rows_to_process)} 筆重複標題錯誤。")

    # 測試模式：只處理第一筆
    if args.test:
        print("  ℹ️ [測試模式] 僅處理此檔案的第一筆錯誤。")
        rows_to_process = rows_to_process.head(1)

    processed_count = 0

    for index in rows_to_process.index:
        original_title = df.at[index, "Title"]
        description = df.at[index, "Description"]

        if pd.isna(description) or not str(description).strip():
            print(f"    ⚠️ Index {index}: Description 為空，無法生成新標題。")
            continue

        print(f"    Processing Index {index}...")

        new_title = generate_new_title_from_description(str(description))

        if "ERROR:" not in new_title and "Simulated" not in new_title:
            df.at[index, "Title"] = new_title
            df.at[index, "error"] = pd.NA  # 清除錯誤標記
            print(f"      ✓ 新標題: {new_title}")
            processed_count += 1
        elif "Simulated" in new_title:
            # 模擬模式也要假裝成功更新
            df.at[index, "Title"] = new_title
            print(f"      ✓ (模擬)新標題: {new_title}")
            processed_count += 1
        else:
            print(f"      ⚠️ 生成失敗，保留原樣。")

        time.sleep(1)  # 避免 API Rate Limit

    # 儲存結果
    if processed_count > 0:
        try:
            df.to_csv(output_path, index=False, encoding="utf-8")
            print(f"  ✓ 成功！已修正 {processed_count} 筆。")
            print(f"  💾 已儲存至: {os.path.basename(output_path)}")
        except Exception as e:
            print(f"  ❌ 儲存失敗: {e}")
    else:
        print("  ℹ️ 沒有資料被修改，不建立新檔案。")


# ------------------- 主程式 -------------------
def main():

    parser = argparse.ArgumentParser(
        description="Fix duplicate titles in ALL CSV files in the folder."
    )
    parser.add_argument(
        "-t",
        "--test",
        action="store_true",
        help="Run in test mode (processes only the first error of each file).",
    )
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))

    if args.test:
        print("\n*** 🏃‍♂️ 執行模式：測試模式 (每個檔案只修第一筆) 🏃‍♂️ ***")
    else:
        print("\n--- 開始批次處理資料夾內的所有 CSV ---")

    # 取得所有 CSV 檔案
    all_files = [f for f in os.listdir(script_dir) if f.endswith(".csv")]

    # 過濾掉已經是 _fixed 的檔案，避免重複處理
    target_files = [f for f in all_files if not f.endswith("_fixed.csv")]

    if not target_files:
        print("❌ 當前目錄下沒有找到需要處理的 CSV 檔案。")
        return

    print(f"ℹ️ 總共發現 {len(target_files)} 個潛在的 CSV 檔案。")

    # 開始迴圈處理
    for filename in target_files:
        input_csv_path = os.path.join(script_dir, filename)

        # 建立輸出檔名： filename.csv -> filename_fixed.csv
        base_name = os.path.splitext(filename)[0]
        output_filename = f"{base_name}_fixed.csv"
        output_csv_path = os.path.join(script_dir, output_filename)

        # 呼叫處理函數
        process_single_csv(input_csv_path, output_csv_path, args)

    print(f"\n--- 所有檔案處理完畢 ---")


if __name__ == "__main__":
    main()
