import os
import sys
from dotenv import dotenv_values
from google import genai

# ==========================================
# 📂 設定路徑
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")

print("-" * 50)
print(f"📂 讀取路徑: {ENV_PATH}")

if not os.path.exists(ENV_PATH):
    print(f"❌ 錯誤：找不到 .env 檔案！")
    sys.exit(1)

env_config = dotenv_values(ENV_PATH)
GEMINI_API_KEY = env_config.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("❌ .env 內沒有 GEMINI_API_KEY")
    sys.exit(1)

print(f"🔑 API Key: {GEMINI_API_KEY[:5]}...OK")

# ==========================================
# 📡 查詢模型
# ==========================================
try:
    print("\n📡 正在連線 Google 查詢...")
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    print("📋 可用模型清單 (請將此名稱填入 Excel):")
    print("=" * 40)
    
    # 直接列出所有模型，不過濾屬性，避免報錯
    count = 0
    for m in client.models.list():
        # 確保只列出 gemini 相關的模型
        if "gemini" in m.name.lower():
            # 有些 SDK 版本 name 包含 'models/', 有些沒有，這裡做個處理
            raw_name = m.name
            clean_name = raw_name.split("/")[-1] # 只取最後一段，例如 gemini-1.5-flash
            
            print(f"   ✅ {clean_name}")
            count += 1
            
    if count == 0:
        print("⚠️ 連線成功，但沒有列出任何 Gemini 模型 (可能是權限問題)")

except Exception as e:
    print(f"\n❌ 查詢失敗: {e}")
    # 印出物件的所有屬性，方便除錯（如果還失敗的話）
    try:
        if 'm' in locals():
            print(f"DEBUG: 模型物件屬性: {dir(m)}")
    except: pass

print("=" * 40)
input("按 Enter 鍵離開...")
