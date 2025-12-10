print("🚀 System initializing... Please wait while libraries are loading.")
import sys
import os
import re
import time
import warnings
import random
import logging
import threading
import io 
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from dotenv import dotenv_values
from PIL import Image
import pandas as pd
from google import genai
from google.genai import types 
from google.genai.errors import APIError
from jinja2 import Template
import multiprocessing
import shutil 
import mimetypes

# 忽略 pandas 的 FutureWarning
warnings.filterwarnings("ignore")

# =======================================================
# 📂 核心路徑與 Log 設定
# =======================================================
def get_base_path():
    """判斷 EXE 或 Python 環境，回傳根目錄"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_path()

# 設定 Log 資料夾與檔案
LOG_FOLDER = os.path.join(BASE_DIR, "Logs")
os.makedirs(LOG_FOLDER, exist_ok=True)
current_time_str = datetime.now().strftime('%Y%m%d-%H%M%S')
LOG_FILE_PATH = os.path.join(LOG_FOLDER, f"log_image_gen-{current_time_str}.txt")

# 🔥 設定 Logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE_PATH, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

def log(msg):
    logging.info(msg)

# 🔥 啟動畫面
print("-" * 50)
log(f"🚀 Generic Batch Image Generator")
log(f"📂 Working Directory: {BASE_DIR}")
log(f"📝 Log file: {LOG_FILE_PATH}")
print("-" * 50)

# 設定其他檔案路徑
ENV_FILE_PATH = os.path.join(BASE_DIR, ".env")
OUTPUT_FOLDER = os.path.join(BASE_DIR, "Generated_Images")
INSTRUCTION_FILE = os.path.join(BASE_DIR, "image_generation_instruction.txt")

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# 全域 Client 變數 (供 thread 使用)
global_client = None
use_mock = False

# ------------------- Helper functions -------------------
def ensure_template_exists(path, default_text):
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(default_text.strip())

def load_template(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def normalize_cols(df):
    # 轉小寫、去空白、並將「空格」取代為「底線」
    df.columns = df.columns.str.strip().str.lower().str.replace(' ', '_')
    return df

# Self-Healing: Check for required files
def initialize_image_system():
    required_files = ["Config_Data.xlsx", "image_generation_instruction.txt", ".env"]
    base_path = sys._MEIPASS if getattr(sys, 'frozen', False) else ""
    if not base_path: return

    log("🔍 Checking system files (Image Mode)...")
    for filename in required_files:
        if not os.path.exists(filename):
            source = os.path.join(base_path, filename)
            target = os.path.join(os.getcwd(), filename)
            if os.path.exists(source):
                try:
                    shutil.copy2(source, target)
                    log(f"   ✅ Restored: {filename}")
                except Exception as e:
                    log(f"   ❌ Failed to restore {filename}: {e}")

# 支援多種欄位名稱以相容 Generated Content 檔案
COL_ALIASES = {
    'ID': ['id', 'product_id'],
    'Prompt': ['prompt', 'image_prompt_for_ai'],
    'Image_name': ['image_name', 'image_reference'] 
}

def get_col_value(row, col_key):
    """嘗試從多個別名中取得欄位值"""
    aliases = COL_ALIASES.get(col_key, [col_key.lower()])
    for alias in aliases:
        if alias in row:
            return row[alias]
    return None

def call_api_with_retry(api_func, *args, retry_settings=None, **kwargs):
    """
    呼叫 API 並帶有重試機制，讀取 Config 中的設定
    """
    # 預設值
    max_retries = 3
    initial_backoff = 5
    
    # 從 settings 讀取
    if retry_settings:
        max_retries = retry_settings.get('max_retries', 3)
        initial_backoff = retry_settings.get('retry_backoff', 5)

    attempt = 0
    while attempt <= max_retries:
        try:
            return api_func(*args, **kwargs)
        except Exception as e:
            error_str = str(e).lower()
            # 針對 Rate Limit (429) 或 Resource Exhausted 進行重試
            if "429" in error_str or "resource_exhausted" in error_str:
                attempt += 1
                if attempt > max_retries:
                    raise e # 超過次數，拋出錯誤
                
                wait_time = initial_backoff * attempt # 線性或指數退避
                log(f"⚠️ API Busy (429), retrying ({attempt}/{max_retries}) in {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise e # 其他錯誤直接拋出

def validate_aspect_ratio_support(model_name, current_ratio, ratios_df):
    """
    🔥 檢查當前模型是否支援選定的長寬比 (已優化顯示格式：去除秒數與開頭0)
    """
    # 內部小函式：用來清理格式 (例如 09:16:00 -> 9:16)
    def clean_ratio_fmt(val):
        s = str(val).strip()
        if s.count(':') >= 2: # 去除秒數 (09:16:00 -> 09:16)
            s = s.rsplit(':', 1)[0]
        if s.startswith('0'): # 去除開頭 0 (09:16 -> 9:16)
            s = s[1:]
        return s

    if ratios_df.empty:
        return "1:1"

    # 1. 清理傳入的當前比例
    clean_current = clean_ratio_fmt(current_ratio)

    # 2. 找出 Excel 中對應的那一行 (需比對清理後的數值)
    row = pd.DataFrame()
    for _, r in ratios_df.iterrows():
        if clean_ratio_fmt(r['aspect_ratio']) == clean_current:
            row = r.to_frame().T
            break
    
    # 如果找不到對應設定，暫時回傳清理後的數值 (容錯)
    if row.empty:
        return clean_current

    supported_models_str = str(row.iloc[0].get('supported_models', 'All')).lower().strip()
    
    # 3. 檢查相容性
    is_compatible = False
    model_lower = model_name.lower()

    if 'all' in supported_models_str: is_compatible = True
    elif 'gemini' in supported_models_str and 'gemini' in model_lower: is_compatible = True
    elif 'imagen' in supported_models_str and 'imagen' in model_lower: is_compatible = True
    # 排除例外
    if 'gemini only' in supported_models_str and 'imagen' in model_lower: is_compatible = False
    
    if is_compatible:
        return clean_current

    # 4. 衝突時顯示選單 (這裡套用清理邏輯)
    print(f"\n⚠️  CONFLICT: Ratio '{clean_current}' is marked as '{row.iloc[0]['supported_models']}',")
    print(f"    but you selected model: '{model_name}'.")
    print("\n👉  Please select a compatible Aspect Ratio:")

    valid_options = []
    seen = set() # 用來過濾重複 (例如 9:16 和 09:16:00 清理後是一樣的)

    for _, r_row in ratios_df.iterrows():
        s_str = str(r_row.get('supported_models', 'All')).lower()
        opt_compatible = False
        if 'all' in s_str: opt_compatible = True
        elif 'gemini' in s_str and 'gemini' in model_lower: opt_compatible = True
        elif 'imagen' in s_str and 'imagen' in model_lower: opt_compatible = True
        
        if opt_compatible:
            fmt_opt = clean_ratio_fmt(r_row['aspect_ratio'])
            if fmt_opt not in seen:
                valid_options.append(fmt_opt)
                seen.add(fmt_opt)

    for i, opt in enumerate(valid_options):
        print(f"   [{i+1}] {opt}")
    print("   [Q] Quit")

    while True:
        choice = input("👉 Select Option (Number): ").strip().lower()
        if choice == 'q':
            print("❌ User aborted.")
            sys.exit()
        
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(valid_options):
                new_ratio = valid_options[idx]
                print(f"✅  Switched Aspect Ratio to: {new_ratio}")
                return new_ratio
        
        print("   Invalid selection. Try again.")

# =======================================================
# 🧩 核心處理邏輯 (Process Item)
# =======================================================
# 🔥 修改點 1: 在最後面新增 excel_filename 參數
def process_single_item(row, target_ratio, sheet_name, model_name, use_ref, instruction, col_map, retry_settings, excel_filename):
    """
    雙引擎處理邏輯 + 顯示存檔路徑 (最終版：自動建立資料夾 + 自動偵測副檔名)
    """
    try:
        item_id = str(row[col_map['ID']] if col_map['ID'] in row else 'Unknown').strip()
        prompt_text = str(row[col_map['Prompt']] if col_map['Prompt'] in row else '').strip()
    except:
        return {"error": "Column read error"}
    
    # 處理 Aspect Ratio
    ar_val = str(target_ratio if target_ratio else '1:1').strip()
    if ar_val.count(':') == 2: ar_val = ar_val.rsplit(':', 1)[0]
    if ar_val.startswith('0'): ar_val = ar_val[1:]
    ratio_name = ar_val.replace(':', 'x')
    
    final_prompt_text = f"{instruction}\n\nAspect Ratio: {ar_val}\nPrompt: {prompt_text}"

    image_bytes = None
    input_mime_type = "image/jpeg"
    
    # 讀取參考圖
    if use_ref:
        img_col = col_map.get('Image_name')
        img_name = str(row[img_col] if img_col and img_col in row else '').strip()
        if img_name:
            possible_paths = [os.path.join(BASE_DIR, "ref_image", img_name), os.path.join(BASE_DIR, img_name)]
            found_img_path = next((p for p in possible_paths if os.path.exists(p)), None)
            if not found_img_path: return {"error": f"Ref Image Not Found: {img_name}"}
            try:
                if found_img_path.lower().endswith(".png"): input_mime_type = "image/png"
                elif found_img_path.lower().endswith(".webp"): input_mime_type = "image/webp"
                with open(found_img_path, "rb") as image_file: image_bytes = image_file.read()
            except Exception as e: return {"error": f"Invalid Image File: {e}"}

    try:
        if 'use_mock' in globals() and use_mock:
            time.sleep(0.1)
            return {"status": "Mock Success", "path": f"mock/{excel_filename}/{item_id}.png"}

        img_result_data = None
        output_ext = ".png" # 預設值，萬一偵測失敗時用
        
        is_imagen = 'imagen' in model_name.lower()
        
        # ==========================================
        # 🅰️ 路線 A: Imagen (Generate Images)
        # ==========================================
        if is_imagen:
            if image_bytes: return {"error": "Imagen model does not support Ref Image. Switch to Gemini."}
            
            # 這裡我們還是請求 jpeg，但下方存檔時會再次確認
            config_params = {'number_of_images': 1, 'aspect_ratio': ar_val, 'output_mime_type': "image/jpeg"}
            
            response = call_api_with_retry(
                global_client.models.generate_images, 
                model=model_name, prompt=final_prompt_text, config=config_params, retry_settings=retry_settings
            )
            if response.generated_images: 
                img_result_data = response.generated_images[0].image.image_bytes
                # 雖然我們要求了 jpeg，但為了保險，這裡也可以留個預設值，或者直接用 .jpg
                output_ext = ".jpg" 
            else: 
                return {"error": "Imagen returned no images"}
        
        # ==========================================
        # 🅱️ 路線 B: Gemini (Generate Content)
        # ==========================================
        else:
            parts = [types.Part.from_text(text=final_prompt_text)]
            if image_bytes: parts.append(types.Part.from_bytes(data=image_bytes, mime_type=input_mime_type))
            gen_config = types.GenerateContentConfig(response_modalities=["IMAGE"])
            
            response = call_api_with_retry(
                global_client.models.generate_content,
                model=model_name, contents=[types.Content(role="user", parts=parts)], config=gen_config, retry_settings=retry_settings
            )
            if response.candidates:
                for candidate in response.candidates:
                    if candidate.content and candidate.content.parts:
                        for part in candidate.content.parts:
                            if part.inline_data and part.inline_data.data:
                                img_result_data = part.inline_data.data
                                
                                # 🔥 核心修改：使用 mimetypes 偵測 Gemini 回傳的真實格式
                                if part.inline_data.mime_type:
                                    guessed = mimetypes.guess_extension(part.inline_data.mime_type)
                                    if guessed:
                                        output_ext = guessed
                                        if output_ext == ".jpe": output_ext = ".jpg" # 修正 Python 怪癖
                                break
                    if img_result_data: break
            if not img_result_data: return {"error": f"Gemini Refused: {response.text[:100] if response.text else 'No content'}"}

        # ==========================================
        # 🏁 存檔 (通用邏輯)
        # ==========================================
        if img_result_data:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            clean_sheet = re.sub(r'[\\/*?:"<>|]', "", str(sheet_name))
            clean_id = re.sub(r'[\\/*?:"<>|]', "", str(item_id))
            
            excel_subfolder = os.path.join(OUTPUT_FOLDER, excel_filename)
            os.makedirs(excel_subfolder, exist_ok=True)

            # 檔名組合：使用上面偵測到的 output_ext
            filename = f"{clean_sheet}_{clean_id}_{ratio_name}_{timestamp}{output_ext}"
            save_path = os.path.join(excel_subfolder, filename)
            
            with open(save_path, "wb") as f:
                f.write(img_result_data)
            
            return {"status": "Success", "path": save_path}
        else:
            return {"error": "Unknown error: No data extracted"}

    except Exception as e:
        return {"error": str(e)}
          
def select_config_file():
    """
    掃描當前目錄下所有以 'Config_Data' 開頭的 Excel 檔案。
    - 0 個: 回傳 None
    - 1 個: 自動回傳路徑
    - 多個: 讓使用者選擇
    """
    try:
        current_dir = BASE_DIR
        # 搜尋 Config_Data 開頭且是 Excel 的檔案，排除暫存檔(~$開頭)
        config_files = [
            f for f in os.listdir(current_dir) 
            if f.lower().startswith("config_data") 
            and f.lower().endswith((".xlsx", ".xls")) 
            and not f.startswith("~$")
        ]
        config_files.sort()

        # 情境 1: 沒找到檔案
        if not config_files:
            return None

        # 情境 2: 只有一個檔案 -> 自動選取
        if len(config_files) == 1:
            selected_path = os.path.join(current_dir, config_files[0])
            log(f"✅ Auto-detected Config File: {config_files[0]}")
            return selected_path

        # 情境 3: 多個檔案 -> 使用者選擇
        print("\n" + "="*50)
        print(f" 📂 [Select Configuration] Found {len(config_files)} files:")
        print("="*50)
        
        for idx, file_name in enumerate(config_files):
            # 如果是標準名稱，標記為 Default (選擇性顯示)
            mark = " (Standard)" if file_name == "Config_Data.xlsx" else ""
            print(f"  [{idx + 1}] {file_name}{mark}")
            
        print("="*50)

        while True:
            selection = input(f"👉 Enter number (1-{len(config_files)}) to select: ").strip()
            
            # 允許直接按 Enter 選第一個
            if selection == "":
                log(f"✅ Using first option: {config_files[0]}")
                return os.path.join(current_dir, config_files[0])
            
            if selection.isdigit():
                idx = int(selection) - 1
                if 0 <= idx < len(config_files):
                    selected_file = config_files[idx]
                    log(f"✅ User selected Config: {selected_file}")
                    return os.path.join(current_dir, selected_file)
            print("⚠️ Invalid input. Please enter a valid number.")

    except Exception as e:
        log(f"❌ Error scanning config files: {e}")
        return None
    
# =======================================================
# ⚙️  設定與輔助函式
# =======================================================
def load_settings(config_path):
    """
    讀取 Config_Data.xlsx
    🔥 修正：完整讀取 Concurrency_Config 並打包成 retry_settings
    """
    settings = { 
        "model_name": "gemini-2.5-flash-image", 
        "aspect_ratio": "1:1", 
        "max_workers": 1,
        "retry_settings": {"max_retries": 3, "retry_backoff": 5}, # 預設值
        "ratios_df": pd.DataFrame(),
        "models_df": pd.DataFrame()  # 🔥 新增：用來存放完整的模型設定表
    }
    
    if not os.path.exists(config_path): 
        log(f"⚠️ Config file not found at {config_path}. Using defaults.")
        return settings

    try:
        # 1. Model Config
        try:
            df = pd.read_excel(config_path, sheet_name='Model_Config')
            df = normalize_cols(df)
            settings["models_df"] = df # 🔥 保存完整 DataFrame
            
            is_selected = df['selection'].astype(str).str.lower().isin(['true', '1', 'yes', 'y', 'on'])
            is_image_type = df['model_type'].astype(str).str.strip().str.lower() == 'image'
            
            sel = df[is_selected & is_image_type]
            
            if not sel.empty: 
                settings["model_name"] = str(sel.iloc[0].get('model_name', settings["model_name"])).strip()
                log(f"✅ Loaded Image Model from Config: {settings['model_name']}")
            else:
                log("⚠️ No valid 'Image' model selected in Config. Using default.")
        except Exception as e:
            log(f"⚠️ Error reading Model_Config: {e}")

        # 2. Concurrency Config (🔥 完整讀取)
        try:
            df = pd.read_excel(config_path, sheet_name='Concurrency_Config')
            df = normalize_cols(df)
            d = dict(zip(df['parameter'].astype(str).str.upper(), df['value']))
            
            # 讀取 Max Workers
            if 'MAX_WORKERS' in d: 
                settings["max_workers"] = int(float(d['MAX_WORKERS']))
            
            # 讀取 Retry 相關設定
            retry_config = {}
            if 'API_RETRY_ATTEMPTS' in d:
                retry_config['max_retries'] = int(float(d['API_RETRY_ATTEMPTS']))
            if 'RETRY_INITIAL_BACKOFF' in d:
                retry_config['retry_backoff'] = int(float(d['RETRY_INITIAL_BACKOFF']))
            
            # 更新 settings
            settings["retry_settings"].update(retry_config)
            
            log(f"✅ Loaded Concurrency: Workers={settings['max_workers']}, Retries={settings['retry_settings']['max_retries']}")

        except Exception as e:
            log(f"⚠️ Error reading Concurrency_Config: {e}")

        # 3. Aspect Ratio
        try:
            df = pd.read_excel(config_path, sheet_name='Aspect_Ratio')
            df = normalize_cols(df)
            settings["ratios_df"] = df

            is_selected = df['selection'].astype(str).str.lower().isin(['true', '1', 'yes', 'y', 'on'])
            sel_ar = df[is_selected]
            
            if not sel_ar.empty:
                raw_ar = str(sel_ar.iloc[0].get('aspect_ratio', '1:1')).strip()
                settings["aspect_ratio"] = raw_ar
                log(f"✅ Loaded Aspect Ratio from Config: {settings['aspect_ratio']}")
            else:
                log("⚠️ No Aspect Ratio selected in Config. Defaulting to 1:1.")
                
        except Exception as e:
            log(f"⚠️ Error reading Aspect_Ratio: {e}")

    except Exception as e: 
        log(f"⚠️ Error reading config: {e}")
    return settings

def configure_runtime_settings(initial_model_name, models_df):
    print("\n" + "="*30 + "\n   🛠️  RUNTIME SETTINGS\n" + "="*30)
    
    # 1. 設定測試模式
    t_in = input("👉 Run single test mode? (Y/N) [default: Y]: ").strip().upper()
    test_single = False if t_in == 'N' else True
    
    # 2. 設定參考圖模式
    r_in = input("👉 Do you want to upload a reference image? (Y/N) [default: N]: ").strip().upper()
    use_ref = True if r_in == 'Y' else False

    # 3. 準備合法模型名單 (Candidate List)
    valid_models = []
    default_img2img_models = [
        "gemini-3-pro-image-preview",
        "gemini-2.5-flash-image",
        "gemini-2.5-flash-image-preview"
    ]

    if not models_df.empty:
        try:
            if use_ref:
                # 篩選 Image_To_Image == True 的模型
                mask = models_df['image_to_image'].astype(str).str.lower().isin(['true', '1', 'yes', 'y', 'on'])
                valid_models = models_df[mask]['model_name'].tolist()
            else:
                # 一般模式：所有 Model_Type 為 'Image' 的都行
                mask = models_df['model_type'].astype(str).str.lower() == 'image'
                valid_models = models_df[mask]['model_name'].tolist()
        except Exception as e:
            log(f"⚠️ Error filtering models: {e}")
    
    # Fallback: 如果清單為空，使用預設值
    if not valid_models:
        if use_ref:
            valid_models = default_img2img_models
        else:
            valid_models = default_img2img_models + ["imagen-4.0-generate-001"]

    # 4. 檢查 Config 模型是否適用 (關鍵優化邏輯)
    final_model = initial_model_name.strip()
    is_compatible = final_model in valid_models

    if is_compatible:
        # ✅ 情境 A: 模型完美適用 -> 直接鎖定，不詢問
        print("-" * 30)
        print(f"✅ Using Configured Model: [{final_model}]")
        print(f"   (Compatible with {'Ref Image' if use_ref else 'Text-to-Image'} mode)")
    else:
        # ⚠️ 情境 B: 模型不適用 或 未選取 -> 觸發選單
        print("-" * 30)
        if final_model:
            print(f"⚠️  Configured model '{final_model}' is NOT compatible with {'Ref Image' if use_ref else 'Text-to-Image'} mode.")
        
        # 自動切換到第一個合法模型作為預設
        final_model = valid_models[0]
        print(f"🔄  Recommended: {final_model}")
        print("👉  Please select a valid model:")
        
        for idx, m in enumerate(valid_models):
            mark = " (Recommended)" if m == final_model else ""
            print(f"   [{idx+1}] {m}{mark}")
        
        while True:
            sel = input("👉 Enter number (or press Enter to use Recommended): ").strip()
            if sel == "":
                print(f"✅ Selected: {final_model}")
                break 
            
            if sel.isdigit():
                idx = int(sel) - 1
                if 0 <= idx < len(valid_models):
                    final_model = valid_models[idx]
                    print(f"✅ Selected: {final_model}")
                    break
            print("⚠️ Invalid selection. Please enter a valid number.")

    # 5. 最終狀態顯示
    print("-" * 30)
    print(f"🤖 Final Model : {final_model}")
    print(f"🧪 Test Mode   : {'ON' if test_single else 'OFF'}")
    print(f"🖼️  Ref Image   : {'ON' if use_ref else 'OFF'}")
    print("-" * 30 + "\n")
    
    return test_single, use_ref, final_model

def find_actual_col_name(df_cols, key_alias):
    aliases = COL_ALIASES.get(key_alias, [key_alias.lower()])
    for alias in aliases:
        if alias in df_cols:
            return alias
    return None

# =======================================================
# 🚀 主程式 (Main)
# =======================================================
if __name__ == '__main__':
    multiprocessing.freeze_support()
    
    try:
        initialize_image_system()
        default_instruction = "Generate a high-quality image based on the prompt."
        ensure_template_exists(INSTRUCTION_FILE, default_instruction)

        log("\n--- API Setup ---")
        env_config = dotenv_values(ENV_FILE_PATH)
        GEMINI_API_KEY = env_config.get("GEMINI_API_KEY")
        
        if not GEMINI_API_KEY:
            log(f"⚠️ GEMINI_API_KEY not detected in .env")
            use_mock = input("   ❌ Use simulation (Mock) mode? (Y/N): ").lower() == 'y'
            if not use_mock: sys.exit()
        else:
            try:
                global_client = genai.Client(api_key=GEMINI_API_KEY)
                log("✓ Global Gemini Client initialized.")
            except Exception as e:
                log(f"❌ API Client Init Error: {e}")
                sys.exit(1)

        instruction_content = load_template(INSTRUCTION_FILE)

        # (新版優化)
        target_config_path = select_config_file()

        if target_config_path:
            log(f"⏳ Loading settings from: {os.path.basename(target_config_path)}...")
            settings = load_settings(target_config_path)
        else:
            # 沒找到檔案時的明顯提示
            print("\n" + "!"*60)
            log("⚠️  NO CONFIGURATION FILE FOUND (Config_Data*.xlsx)")
            log("👉  System will run with [DEFAULT SETTINGS] (Gemini, 1:1, etc.)")
            print("!"*60 + "\n")
            # 傳入一個不存在的路徑，強制 load_settings 回傳預設值
            settings = load_settings("DUMMY_PATH_FOR_DEFAULTS")
        
        test_single, use_ref_image, target_model = configure_runtime_settings(
            settings["model_name"], 
            settings["models_df"]
        )
        validated_ratio = validate_aspect_ratio_support(target_model, settings["aspect_ratio"], settings["ratios_df"])

        default_folder = "Generated_Content"
        f_in = input(f"👉 Enter input folder name (default: '{default_folder}'): ").strip()
        target_folder_name = f_in if f_in else default_folder
        target_folder_path = os.path.join(BASE_DIR, target_folder_name)

        if not os.path.exists(target_folder_path):
            print(f"❌ Folder '{target_folder_name}' not found. Scanning root directory instead...")
            target_folder_path = BASE_DIR
        
        all_files = [f for f in os.listdir(target_folder_path) if f.lower().endswith(('.xlsx', '.xls')) and not f.startswith('~$')]
        all_files = [f for f in all_files if "config_data" not in f.lower()]

        if not all_files:
            log("❌ No valid Excel files found. Exiting.")
            sys.exit()

        print(f"📂 Found {len(all_files)} Excel file(s).")
        print(f"🚀 Initializing Generator with model: [{target_model}]")
        print(f"📐 Target Aspect Ratio: [{validated_ratio}]")
        time.sleep(1)

        for file_name in all_files:
            file_path = os.path.join(target_folder_path, file_name)
            
            # 🔥 [修正點 1] 取得不含副檔名的檔名 (例如: Generated_Content_20251209)
            excel_clean_name = os.path.splitext(file_name)[0]

            log(f"\n📦 Processing File: {file_name}")
            
            try:
                xls = pd.ExcelFile(file_path)
            except Exception as e:
                log(f"❌ Read Error: {e}")
                continue

            excluded_sheets = ['config', 'ratios', 'dropdowns', 'lists', 'data validation', 'readme', 'model_config']
            
            for sheet in xls.sheet_names:
                if sheet.lower() in excluded_sheets: continue
                
                try:
                    df = pd.read_excel(file_path, sheet_name=sheet).fillna('')
                    df = normalize_cols(df)
                except: continue

                id_col = find_actual_col_name(df.columns, 'ID')
                prompt_col = find_actual_col_name(df.columns, 'Prompt')
                if not id_col or not prompt_col: continue 

                col_map = {'ID': id_col, 'Prompt': prompt_col}
                if use_ref_image:
                    img_col = find_actual_col_name(df.columns, 'Image_name')
                    if not img_col:
                        log(f"  ⚠️  Sheet '{sheet}': Ref Image ON but 'Image_name' column missing. Skipping.")
                        continue
                    col_map['Image_name'] = img_col

                log(f"  📂 Sheet: {sheet}")

                jobs = []
                for _, row in df.iterrows():
                    if not str(row[id_col]).strip() or not str(row[prompt_col]).strip(): continue
                    
                    # 🔥 [修正點 2] 補上最後一個參數 excel_clean_name
                    jobs.append((
                        row, 
                        validated_ratio, 
                        sheet, 
                        target_model, 
                        use_ref_image, 
                        instruction_content, 
                        col_map, 
                        settings["retry_settings"],
                        excel_clean_name  # <--- 這裡必須加上
                    ))
                    
                    if test_single: break
                
                if not jobs:
                    log("     ℹ️  No valid jobs.")
                    continue

                log(f"     🔥 Starting {len(jobs)} tasks (Max Workers: {settings['max_workers']})...")
                
                # 執行緒池 (這部分不用動，因為 jobs 已經修正了)
                with ThreadPoolExecutor(max_workers=settings["max_workers"]) as executor:
                    futures = {executor.submit(process_single_item, *j): j for j in jobs}
                    for i, f in enumerate(as_completed(futures)):
                        res = f.result()
                        if "error" in res:
                            print(f"\n     ❌ Error: {res['error']}")
                        else:
                            print(f"\n     ✅ Saved: {res['path']}")

                if test_single: 
                    print("  🛑 Test mode: Stopping after first active sheet.")
                    break

    except Exception as e:
        log(f"\n❌ Fatal Error: {e}")
        import traceback
        traceback.print_exc()
    
    input("\n✅ Execution finished. Press Enter to exit...")