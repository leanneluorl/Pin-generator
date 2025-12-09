import os
import sys
import time
from dotenv import dotenv_values
from PIL import Image
from google import genai
from google.genai.errors import ClientError

# ==========================================
# 📍 1. 自動定位程式位置 (關鍵步驟)
# ==========================================
def get_base_path():
    """
    不管是在 VS Code 執行，還是打包成 EXE，
    這個函式都能找到正確的「根目錄」位置。
    """
    if getattr(sys, 'frozen', False):
        # 如果是打包後的 EXE
        return os.path.dirname(sys.executable)
    else:
        # 如果是 Python 腳本
        return os.path.dirname(os.path.abspath(__file__))

# 取得目前程式的根目錄
BASE_DIR = get_base_path()
print(f"📂 程式根目錄: {BASE_DIR}")

# ==========================================
# 🔑 2. 設定與載入 Key
# ==========================================
ENV_PATH = os.path.join(BASE_DIR, ".env")
config = dotenv_values(ENV_PATH)
API_KEY = config.get("GEMINI_API_KEY")

# 指定圖片路徑
IMAGE_FOLDER = os.path.join(BASE_DIR, "product_image")
IMAGE_FILENAME = "sample.jpg"  # 👈 請確保檔名正確
IMAGE_PATH = os.path.join(IMAGE_FOLDER, IMAGE_FILENAME)

# ==========================================
# 🚀 3. 主測試程式
# ==========================================
def test_image_process():
    print("\n" + "="*50)
    print("🖼️  Gemini 圖片上傳測試工具")
    print("="*50)

    # 1. 檢查 API Key
    if not API_KEY:
        print("❌ 錯誤：找不到 API Key，請檢查 .env 檔案。")
        return
    
    # 2. 檢查圖片是否存在
    print(f"🔍 正在尋找圖片: {IMAGE_PATH}")
    if not os.path.exists(IMAGE_PATH):
        print(f"❌ 錯誤：找不到圖片檔案！")
        print(f"   請確認 'product_image' 資料夾內是否有 '{IMAGE_FILENAME}'")
        return
    else:
        print("✅ 圖片檔案存在。")

    # 3. 使用 Pillow (PIL) 讀取圖片
    try:
        img = Image.open(IMAGE_PATH)
        print(f"✅ 圖片讀取成功！尺寸: {img.size}, 格式: {img.format}")
    except Exception as e:
        print(f"❌ 圖片讀取失敗 (可能是格式損壞): {e}")
        return

    # 4. 初始化 Client
    client = genai.Client(api_key=API_KEY)
    
    # 讓使用者選擇模型 (建議先用 2.5-flash 測試連線)
    default_model = "gemini-2.0-flash"
    print(f"\n👉 請選擇模型 (預設: {default_model})")
    print("   輸入 '2' 切換為 gemini-2.5-flash-lite (較易 429 錯誤)")
    choice = input("   您的選擇 (直接按 Enter 使用預設): ").strip()
    
    model_name = default_model
    if choice == '2':
        model_name = "gemini-2.5-flash-lite"

    print(f"\n📡 正在發送圖片與文字給 [{model_name}] ...")
    
    prompt = "請用繁體中文詳細描述這張圖片的內容，並告訴我這張圖適合什麼樣的 Pinterest 標題。"

    start_time = time.time()

    try:
        # 🔥 核心：同時傳送圖片 (img) 和文字 (prompt)
        response = client.models.generate_content(
            model=model_name,
            contents=[img, prompt]
        )
        
        end_time = time.time()
        duration = end_time - start_time

        print("\n✅ API 回應成功！ (Success)")
        print(f"⏱️ 耗時: {duration:.2f} 秒")
        print("-" * 30)
        print("📝 AI 回覆內容:")
        print(response.text)
        print("-" * 30)

    except ClientError as e:
        print("\n❌ API 錯誤:")
        if "429" in str(e):
            print("🔴 429 Too Many Requests (被限流)。請稍後再試。")
        else:
            print(f"⚠️ {e}")
    except Exception as e:
        print(f"\n❌ 未知錯誤: {e}")

    input("\n測試結束，請按 Enter 離開...")

if __name__ == "__main__":
    test_image_process()
