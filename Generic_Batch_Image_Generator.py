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
    df.columns = df.columns.str.strip().str.lower()
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

def call_api_with_retry(api_func, *args, max_retries=3, **kwargs):
    attempt = 0
    while attempt <= max_retries:
        try:
            return api_func(*args, **kwargs)
        except Exception as e:
            error_str = str(e).lower()
            if "429" in error_str or "resource_exhausted" in error_str:
                attempt += 1
                time.sleep(5 * attempt)
                log(f"⚠️ API Busy, retrying ({attempt}/{max_retries})...")
            else:
                raise e

# =======================================================
# 🧩 核心處理邏輯 (Process Item) - 雙引擎切換版
# =======================================================
def process_single_item(row, ratio_row, sheet_name, model_name, use_ref, instruction, col_map):
    """
    雙引擎處理邏輯：
    1. 若是 Imagen -> 走 generate_images (僅支援文生圖)
    2. 若是 Gemini -> 走 generate_content (支援文生圖/圖生圖, 設定 response_modalities)
    """
    try:
        item_id = str(row[col_map['ID']] if col_map['ID'] in row else 'Unknown').strip()
        prompt_text = str(row[col_map['Prompt']] if col_map['Prompt'] in row else '').strip()
    except:
        return {"error": "Column read error"}
    
    # 1. 處理長寬比
    if ratio_row is not None and not ratio_row.empty:
        ar_val = str(ratio_row.get('aspect_ratio', '1:1')).strip()
        ratio_name = str(ratio_row.get('ratio_name', 'AR')).strip()
    else:
        ar_val = '1:1'
        ratio_name = '1x1'
    
    final_prompt_text = f"{instruction}\n\nAspect Ratio: {ar_val}\nPrompt: {prompt_text}"

    # 2. 準備圖片 (如果有的話)
    image_bytes = None
    mime_type = "image/jpeg"
    
    if use_ref:
        img_col = col_map.get('Image_name')
        img_name = str(row[img_col] if img_col and img_col in row else '').strip()
        
        if img_name:
            possible_paths = [
                os.path.join(BASE_DIR, "ref_image", img_name),
                os.path.join(BASE_DIR, img_name)
            ]
            found_img_path = next((p for p in possible_paths if os.path.exists(p)), None)
            
            if not found_img_path:
                return {"error": f"Ref Image Not Found: {img_name}"}
            
            try:
                if found_img_path.lower().endswith(".png"): mime_type = "image/png"
                elif found_img_path.lower().endswith(".webp"): mime_type = "image/webp"
                
                with open(found_img_path, "rb") as image_file:
                    image_bytes = image_file.read()
            except Exception as e:
                return {"error": f"Invalid Image File: {e}"}

    try:
        if use_mock:
            time.sleep(0.1)
            return {"status": "Mock Success", "path": "mock.png"}

        img_result_data = None

        # 🔥【分流判斷】
        is_imagen = 'imagen' in model_name.lower()
        
        # ==========================================
        # 🅰️ 路線 A: Imagen (專用 generate_images)
        # ==========================================
        if is_imagen:
            # Imagen 此腳本僅支援文生圖
            if image_bytes:
                return {"error": "Imagen model does not support Ref Image in this script. Switch to Gemini."}

            # 設定 Imagen 參數
            gen_config = types.GenerateImagesConfig(
                aspect_ratio=ar_val if ':' not in ar_val else None,
                number_of_images=1
            )
            
            # 呼叫 Imagen API
            response = call_api_with_retry(
                global_client.models.generate_images, 
                model=model_name, 
                prompt=final_prompt_text, 
                config=gen_config
            )
            
            if response.generated_images:
                img_result_data = response.generated_images[0].image.image_bytes
            else:
                return {"error": "Imagen returned no images"}

        # ==========================================
        # 🅱️ 路線 B: Gemini (通用 generate_content)
        # ==========================================
        else:
            # 準備 Parts (文字 + 圖片)
            parts = [types.Part.from_text(text=final_prompt_text)]
            
            if image_bytes:
                parts.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))

            # 設定 Gemini 參數 (關鍵：response_modalities=["IMAGE"])
            gen_config = types.GenerateContentConfig(
                response_modalities=["IMAGE"],
            )

            # 呼叫 Gemini API
            response = call_api_with_retry(
                global_client.models.generate_content,
                model=model_name,
                contents=[types.Content(role="user", parts=parts)],
                config=gen_config
            )

            # 解析 Gemini 回傳 (inline_data)
            if response.candidates:
                for candidate in response.candidates:
                    if candidate.content and candidate.content.parts:
                        for part in candidate.content.parts:
                            if part.inline_data and part.inline_data.data:
                                img_result_data = part.inline_data.data
                                break
                    if img_result_data: break
            
            if not img_result_data:
                err = response.text[:100] if response.text else "No content"
                return {"error": f"Gemini Refused: {err}"}

        # ==========================================
        # 🏁 存檔 (共通)
        # ==========================================
        if img_result_data:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            clean_sheet = re.sub(r'[\\/*?:"<>|]', "", str(sheet_name))
            clean_id = re.sub(r'[\\/*?:"<>|]', "", str(item_id))
            
            filename = f"{clean_sheet}_{clean_id}_{ratio_name}_{timestamp}.png"
            save_path = os.path.join(OUTPUT_FOLDER, filename)
            
            with open(save_path, "wb") as f:
                f.write(img_result_data)
            
            return {"status": "Success", "path": filename}
        else:
            return {"error": "Unknown error: No data extracted"}

    except Exception as e:
        return {"error": str(e)}

# =======================================================
# ⚙️  設定與輔助函式
# =======================================================
def load_settings(config_path):
    """
    讀取 Config_Data.xlsx 參數
    🔥 第一道過濾：Model_Type 必須為 'Image'
    """
    # 預設值，若 Config 全錯則使用此安全值
    settings = { "model_name": "gemini-2.5-flash-image", "ratios": pd.DataFrame(), "max_workers": 1 }
    
    if not os.path.exists(config_path): 
        log(f"⚠️ Config file not found at {config_path}. Using defaults.")
        return settings

    try:
        # 1. Model Config (過濾 Model_Type)
        try:
            df = pd.read_excel(config_path, sheet_name='Model_Config')
            df = normalize_cols(df)
            
            # 篩選條件：(Selection=True) AND (Model_Type='Image')
            # 允許 'Image' 大小寫不同，去除空格
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

        # 2. Workers
        try:
            df = pd.read_excel(config_path, sheet_name='Concurrency_Config')
            df = normalize_cols(df)
            d = dict(zip(df['parameter'].astype(str).str.upper(), df['value']))
            if 'MAX_WORKERS' in d: settings["max_workers"] = int(float(d['MAX_WORKERS']))
        except: pass

        # 3. Ratios
        try:
            df = pd.read_excel(config_path, sheet_name='Aspect_Ratio')
            df = normalize_cols(df)
            settings["ratios"] = df[df['selection'].astype(str).str.lower().isin(['true', '1', 'yes', 'y'])]
        except: pass

    except Exception as e: 
        log(f"⚠️ Error reading config: {e}")
    return settings

def configure_runtime_settings(initial_model_name):
    """
    詢問用戶設定
    🔥 第二道過濾：若 Ref Image=ON，強制切換至 2.5/3.0 Image
    """
    print("\n" + "="*30 + "\n   🛠️  RUNTIME SETTINGS\n" + "="*30)
    
    # 1. Test Mode
    t_in = input("👉 Run single test mode? (Y/N) [default: Y]: ").strip().upper()
    test_single = False if t_in == 'N' else True
    
    # 2. Ref Image
    r_in = input("👉 Do you want to upload a reference image? (Y/N) [default: N]: ").strip().upper()
    use_ref = True if r_in == 'Y' else False

    # 3. Model Logic (強制切換檢查)
    final_model = initial_model_name
    
    if use_ref:
        # 🛑 規則：上傳圖片模式 (Image-to-Image) 必須是 Gemini Image 模型
        # 檢查邏輯：名稱必須包含 'gemini' 且包含 'image'
        # 排除 imagen，也排除 gemini 純文字版
        
        name_lower = final_model.lower()
        is_valid_img2img = ('gemini' in name_lower) and ('image' in name_lower)
        
        if not is_valid_img2img:
            print(f"⚠️  Model '{final_model}' does not support Image-to-Image.")
            final_model = 'gemini-2.5-flash-image'
            print(f"🔄  Forced switch to: {final_model}")
        else:
            print(f"✅  Reference Image Mode ON. Using: {final_model}")
            
    else:
        # 沒上傳圖片，尊重 Config (此時可能是 Imagen 或 Gemini 文生圖)
        print(f"✅  Model selected: {final_model}")

    # 允許手動最後修改
    print("-" * 30)
    print(f"Current Model: [{final_model}]")
    change_model = input("👉 Do you want to change the model? (Enter new name or Press Enter to skip): ").strip()
    if change_model:
        final_model = change_model
        print(f"✅ Model changed to: {final_model}")

    print("-" * 30)
    print(f"🤖 Final Model : {final_model}")
    print(f"🧪 Test Mode   : {'ON' if test_single else 'OFF'}")
    print(f"🖼️  Ref Image   : {'ON' if use_ref else 'OFF'}")
    print("-" * 30 + "\n")
    return test_single, use_ref, final_model

def find_actual_col_name(df_cols, key_alias):
    """在 DataFrame 的 columns 中尋找符合別名的欄位"""
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
        # 0. 初始化檢查
        initialize_image_system()
        default_instruction = "Generate a high-quality image based on the prompt."
        ensure_template_exists(INSTRUCTION_FILE, default_instruction)

        # 1. API Init
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

        # 2. Load Settings (第一道過濾：Model_Type=Image)
        CONFIG_PATH = os.path.join(BASE_DIR, "Config_Data.xlsx")
        log(f"⏳ Loading base settings from: {os.path.basename(CONFIG_PATH)}...")
        settings = load_settings(CONFIG_PATH)
        
        # 3. Runtime Inputs (第二道過濾：Ref Image 強制切換)
        test_single, use_ref_image, target_model = configure_runtime_settings(settings["model_name"])

        # 4. Folder Input & Scan
        default_folder = "Generated_Content"
        f_in = input(f"👉 Enter input folder name (default: '{default_folder}'): ").strip()
        target_folder_name = f_in if f_in else default_folder
        target_folder_path = os.path.join(BASE_DIR, target_folder_name)

        if not os.path.exists(target_folder_path):
            print(f"❌ Folder '{target_folder_name}' not found. Scanning root directory instead...")
            target_folder_path = BASE_DIR
        
        # 掃描資料夾內的 Excel
        all_files = [f for f in os.listdir(target_folder_path) if f.lower().endswith(('.xlsx', '.xls')) and not f.startswith('~$')]
        # 排除 Config_Data 本身，避免將設定檔當作資料檔處理
        all_files = [f for f in all_files if "config_data" not in f.lower()]

        if not all_files:
            log("❌ No valid Excel files found for processing. Exiting.")
            sys.exit()

        print(f"📂 Found {len(all_files)} Excel file(s) in '{os.path.basename(target_folder_path)}'.")
        print(f"🚀 Initializing Generator with model: [{target_model}]...")
        time.sleep(1)

        # 5. Execution Loop (File -> Sheet -> Row)
        for file_name in all_files:
            file_path = os.path.join(target_folder_path, file_name)
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

                # 檢查必要欄位
                id_col = find_actual_col_name(df.columns, 'ID')
                prompt_col = find_actual_col_name(df.columns, 'Prompt')
                
                if not id_col or not prompt_col:
                    continue 

                col_map = {'ID': id_col, 'Prompt': prompt_col}

                if use_ref_image:
                    img_col = find_actual_col_name(df.columns, 'Image_name')
                    if not img_col:
                        log(f"  ⚠️  Sheet '{sheet}': Ref Image ON but 'Image_name' column missing. Skipping.")
                        continue
                    col_map['Image_name'] = img_col

                log(f"  📂 Sheet: {sheet}")

                # Build Jobs
                jobs = []
                for _, row in df.iterrows():
                    # 基本防呆
                    if not str(row[id_col]).strip() or not str(row[prompt_col]).strip(): continue
                    
                    if not settings["ratios"].empty:
                        for _, r_row in settings["ratios"].iterrows():
                            jobs.append((row, r_row, sheet, target_model, use_ref_image, instruction_content, col_map))
                            if test_single: break
                    else:
                        jobs.append((row, None, sheet, target_model, use_ref_image, instruction_content, col_map))
                    
                    if test_single: break
                
                if not jobs:
                    log("     ℹ️  No valid jobs.")
                    continue

                # Run Threads
                log(f"     🔥 Starting {len(jobs)} tasks...")
                with ThreadPoolExecutor(max_workers=settings["max_workers"]) as executor:
                    futures = {executor.submit(process_single_item, *j): j for j in jobs}
                    for i, f in enumerate(as_completed(futures)):
                        res = f.result()
                        if "error" in res:
                            print(f"\n     ❌ Error: {res['error']}")
                        else:
                            print(".", end="", flush=True)

                print("") 
                if test_single: 
                    print("  🛑 Test mode: Stopping after first active sheet.")
                    break
            
            if test_single: 
                print("\n🛑 Test mode: Stopping after first file.")
                break

    except Exception as e:
        log(f"\n❌ Fatal Error: {e}")
        import traceback
        traceback.print_exc()
    
    input("\n✅ Execution finished. Press Enter to exit...")