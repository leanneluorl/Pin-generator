import os
import sys
import time
from dotenv import dotenv_values
from google import genai
from google.genai.errors import ClientError

# ==========================================
# 🔧 設定區
# ==========================================

# 1. 自動讀取 .env 檔案
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
config = dotenv_values(ENV_PATH)
API_KEY = config.get("GEMINI_API_KEY")

# 2. 如果讀不到，請手動在這裡貼上 Key (測試用)
if not API_KEY:
    # API_KEY = "你的_API_KEY_貼在這裡"
    pass

# ==========================================
# 🚀 測試主程式
# ==========================================

def test_connection():
    print("\n" + "="*50)
    print("🛠️  Gemini API 連線診斷工具")
    print("="*50)

    if not API_KEY:
        print("❌ 錯誤：找不到 API Key！請檢查 .env 檔案或直接在程式碼中設定。")
        return

    print(f"🔑 API Key 狀態: 已讀取 (長度: {len(API_KEY)})")
    
    try:
        client = genai.Client(api_key=API_KEY)
    except Exception as e:
        print(f"❌ Client 初始化失敗: {e}")
        return

    # 讓使用者輸入想測試的模型
    default_model = "gemini-2.5-flash-lite"
    print(f"\n請輸入要測試的模型名稱 (直接按 Enter 使用預設值: {default_model})")
    print("👉 推薦嘗試: gemini-1.5-flash (較穩定)")
    model_name = input("輸入模型名稱: ").strip()
    
    if not model_name:
        model_name = default_model

    print(f"\n📡 正在嘗試連線到模型: [{model_name}] ...")
    print("⏳ 發送測試訊息: 'Hello, verify system status.'")

    start_time = time.time()
    
    try:
        # 發送最簡單的請求
        response = client.models.generate_content(
            model=model_name,
            contents="Hello, simply reply with 'System Operational'."
        )
        
        end_time = time.time()
        duration = end_time - start_time

        print("\n✅ 連線成功！ (Success)")
        print(f"⏱️ 耗時: {duration:.2f} 秒")
        print(f"📝 模型回應: {response.text}")
        print("\n🎉 結論：您的 API Key 和網路環境正常。")

    except ClientError as e:
        print("\n❌ API 錯誤 (ClientError):")
        error_msg = str(e).lower()
        
        if "429" in error_msg or "too many requests" in error_msg:
            print("🔴 狀態: 429 Too Many Requests (被限流)")
            print("👉 原因: 短時間內請求過多，或該模型(Lite/Preview)目前的全球額度已滿。")
            print("👉 建議: 換用 'gemini-1.5-flash' 或等待 30-60 分鐘。")
        elif "404" in error_msg or "not found" in error_msg:
            print("🔴 狀態: 404 Not Found (找不到模型)")
            print(f"👉 原因: 模型名稱 '{model_name}' 可能打錯了，或是該帳號無權限使用此預覽版。")
        elif "403" in error_msg or "permission" in error_msg:
            print("🔴 狀態: 403 Permission Denied (權限不足)")
            print("👉 原因: API Key 可能無效，或該 Key 沒有啟用 Generative Language API。")
        else:
            print(f"⚠️ 詳細錯誤: {e}")

    except Exception as e:
        print(f"\n❌ 未知系統錯誤: {e}")



    input("\n請按 Enter 鍵離開...")

if __name__ == "__main__":
    test_connection()