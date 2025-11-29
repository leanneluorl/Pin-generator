import pandas as pd
# 舊版 Client 導入方式
from google import genai
from google.genai.errors import APIError
import os
from dotenv import load_dotenv
import time
import re
import argparse # <-- 1. 導入 argparse

# ------------------- 載入 API Key -------------------
print("--- 載入設定與 API Key ---")
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ------------------- 初始化 Gemini Client (舊版語法) -------------------
client = None # 先宣告
if not GEMINI_API_KEY:
    print("❌ 錯誤：找不到 GEMINI_API_KEY 環境變數。")
    print("請確保您的 .env 檔案中有 GEMINI_API_KEY。")
else:
    try:
        # 使用 genai.Client()，這符合您原始腳本的用法
        client = genai.Client(api_key=GEMINI_API_KEY)
        print("✓ Gemini Client 已初始化。")
    except Exception as e:
        print(f"❌ 初始化 Gemini Client 時發生錯誤: {e}")

# ------------------- 輔助函數 (Gemini 呼叫) -------------------

def generate_new_title_from_description(description):
    """
    使用 Gemini API 根據描述生成一個新標題。
    (使用 client.models.generate_content 語法)
    """
    
    # 建立一個精簡但明確的 prompt
    prompt = f"""
    Based on the following description, generate a new, unique, and catchy English title under 60 characters.
    The title must be relevant but distinct from any previous titles.
    Only output the new title, nothing else.

    Description:
    "{description}"

    New Title:
    """
    
    if not client:
        print("⚠️ 模擬模式：未呼叫 API (Client 初始化失敗)。")
        time.sleep(0.5) # 模擬 API 延遲
        return f"Simulated New Title for: {description[:30]}..."

    try:
        # 呼叫 API (使用 client.models.generate_content)
        # 確保內容是 list
        response = client.models.generate_content(
            model='gemini-2.5-pro', # 適合此任務的模型
            contents=[prompt] 
        )
        
        # 清理回應
        new_title = response.text.strip()
        
        # 移除可能的引號或標籤
        new_title = re.sub(r'\[?title\]?\s*[:：]\s*', '', new_title, flags=re.IGNORECASE)
        if new_title.startswith('"') and new_title.endswith('"'):
            new_title = new_title[1:-1]
        
        # 確保標題不會太長
        if len(new_title) > 60:
            # 嘗試在最後一個空格處截斷
            last_space = new_title[:60].rfind(' ')
            if last_space != -1:
                new_title = new_title[:last_space]
            else:
                new_title = new_title[:60] # 強制截斷
        
        if not new_title:
             raise ValueError("API 返回了空標題")

        return new_title
    
    except APIError as e:
        print(f"❌ Gemini API 錯誤 (generate_new_title): {e}")
        return "ERROR: API Error"
    except ValueError as e:
        # 處理 .text 屬性不存在或 response 結構不如預期的情況
        print(f"❌ Gemini 回應解析錯誤: {e}")
        try:
            print(f"  - 完整回應 (參考): {response.prompt_feedback}")
        except:
            pass
        return "ERROR: Response Parse Error"
    except Exception as e:
        print(f"❌ 未知錯誤 (generate_new_title): {e}")
        return "ERROR: Unknown Error"

# ------------------- 主程式 -------------------
def main():
    
    # ------------------- 2. Argparse 設定 -------------------
    parser = argparse.ArgumentParser(description="Fix duplicate titles in Pinterest error CSV.")
    parser.add_argument(
        '-t', '--test',
        action='store_true',  # 當參數存在時，儲存 True
        help="Run in single test mode (processes only the first found error)."
    )
    args = parser.parse_args()
    
    if args.test:
        print("\n*** 🏃‍♂️ 執行模式：單筆測試 (Single Test Mode) 🏃‍♂️ ***")
    else:
        print("\n--- 開始處理重複標題的錯誤檔案 (完整模式) ---")
    # ----------------------------------------------------

    try:
        # ------------------- 檔案路徑修正 -------------------
        # 取得 .py 檔案所在的資料夾
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 檔案名稱
        input_filename = "pinterest_bulk_upload_20251110_013246-error.csv"
        output_filename = "pinterest_bulk_upload_reprocessed.csv"
        
        # 組合出絕對路徑
        input_csv = os.path.join(script_dir, input_filename)
        output_csv = os.path.join(script_dir, output_filename)
        
        print(f"ℹ️ 正在從此路徑讀取檔案: {input_csv}")
        # ----------------------------------------------------

        # 嘗試用 'utf-8' 讀取，如果失敗，嘗試 'latin1' 或其他
        try:
            df = pd.read_csv(input_csv, encoding='utf-8')
        except UnicodeDecodeError:
            print("⚠️ 'utf-8' 解碼失敗，嘗試 'latin1' ...")
            df = pd.read_csv(input_csv, encoding='latin1')
            
        print(f"✓ 成功讀取檔案: {input_filename}")
        print(f"  - 總共 {len(df)} 筆資料。")
    except FileNotFoundError:
        print(f"❌ 找不到檔案: {input_csv}")
        print("請確保 CSV 檔案與此程式在同一資料夾中。")
        return
    except Exception as e:
        print(f"❌ 讀取檔案 {input_filename} 時發生錯誤: {e}")
        return
        
    # 檢查必要的欄位
    required_cols = ['Title', 'Description', 'error']
    if not all(col in df.columns for col in required_cols):
        print(f"❌ CSV 檔案中缺少必要的欄位。")
        print(f"  - 需要: {required_cols}")
        print(f"  - 找到: {df.columns.tolist()}")
        return

    # 找出需要處理的 rows
    error_string = "Multiple rows with the same title"
    # 使用 .str.contains() 處理 NaN，並確保是字串
    rows_to_process = df[df['error'].astype(str).str.contains(error_string, na=False)]
    
    if rows_to_process.empty:
        print(f"ℹ️ 在 'error' 欄位中沒有找到 '{error_string}' 的錯誤訊息。")
        print("--- 程式執行完畢，無需處理 ---")
        return
        
    print(f"ℹ️ 找到 {len(rows_to_process)} 筆需要重寫標題的資料。")
    
    # ------------------- 3. 根據 test 參數調整 -------------------
    if args.test:
        print("ℹ️ 單筆測試模式：僅處理第一筆找到的錯誤。")
        # 使用 .head(1) 取得符合條件的第一筆資料
        rows_to_process = rows_to_process.head(1)
    # ---------------------------------------------------------
    
    processed_count = 0
    
    # 遍歷需要處理的 row 的 index (可能是全部，也可能是第一筆)
    for index in rows_to_process.index:
        original_title = df.at[index, 'Title']
        description = df.at[index, 'Description']
        
        # 檢查 description 是否為空
        if pd.isna(description) or not str(description).strip():
            print(f"\n--- 跳過 Index {index} ---")
            print(f"  - 原標題: {original_title}")
            print("  - ⚠️ 錯誤：Description 為空，無法生成新標題。")
            continue

        print(f"\n--- 正在處理 Index {index} ---")
        print(f"  - 原標題: {original_title}")
        print(f"  - 描述 (前 50 字): {str(description)[:50]}...")
        
        # 呼叫 Gemini
        new_title = generate_new_title_from_description(str(description))
        
        # 檢查 API 回應是否成功
        if "ERROR:" not in new_title and "Simulated" not in new_title:
            # 更新 DataFrame 中的標題
            df.at[index, 'Title'] = new_title
            # 清除錯誤訊息
            df.at[index, 'error'] = pd.NA # 使用 pd.NA 更標準
            
            print(f"  ✓ 新標題: {new_title}")
            processed_count += 1
        else:
            print(f"  ⚠️ 產生新標題失敗。保留原標題與錯誤訊息。")
            
        # API 速率限制 (1秒1次)
        # 在單筆測試中這不是必須的，但保留它無害
        time.sleep(1) 

    print(f"\n--- 處理完成 ---")
    
    if args.test and processed_count > 0:
        print(f"✓ 單筆測試完成，已更新 1 筆標題。")
    elif args.test:
         print(f"ℹ️ 單筆測試未執行（可能 Description 為空或 API 失敗）。")
    else:
        print(f"✓ 完整模式完成，總共成功更新了 {processed_count} / {len(rows_to_process)} 筆標題。")

    
    # 儲存到新檔案
    try:
        # 使用 index=False 避免寫入 DataFrame 的 index
        # 使用 encoding='utf-8' 確保相容性
        df.to_csv(output_csv, index=False, encoding='utf-8')
        print(f"✓ 已將結果儲存至: {output_csv}")
    except Exception as e:
        print(f"❌ 儲存檔案 {output_csv} 時發生錯誤: {e}")

    print(f"--- 程式執行完畢 ---")

# ------------------- 執行主程式 -------------------
if __name__ == "__main__":
    main()