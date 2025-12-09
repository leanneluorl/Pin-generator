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
    🔥 檢查當前模型是否支援選定的長寬比
    """
    if ratios_df.empty:
        return "1:1"

    row = ratios_df[ratios_df['aspect_ratio'].astype(str).str.strip() == str(current_ratio).strip()]
    
    if row.empty:
        return current_ratio

    supported_models_str = str(row.iloc[0].get('supported_models', 'All')).lower().strip()
    
    is_compatible = False
    model_lower = model_name.lower()

    if 'all' in supported_models_str:
        is_compatible = True
    elif 'gemini' in supported_models_str and 'gemini' in model_lower:
        is_compatible = True
    elif 'imagen' in supported_models_str and 'imagen' in model_lower:
        is_compatible = True
    if 'gemini only' in supported_models_str and 'imagen' in model_lower:
        is_compatible = False
    
    if is_compatible:
        return current_ratio

    print(f"\n⚠️  CONFLICT: Ratio '{current_ratio}' is marked as '{row.iloc[0]['supported_models']}',")
    print(f"    but you selected model: '{model_name}'.")
    print("\n👉  Please select a compatible Aspect Ratio:")

    valid_options = []
    for _, r_row in ratios_df.iterrows():
        s_str = str(r_row.get('supported_models', 'All')).lower()
        opt_compatible = False
        if 'all' in s_str: opt_compatible = True
        elif 'gemini' in s_str and 'gemini' in model_lower: opt_compatible = True
        elif 'imagen' in s_str and 'imagen' in model_lower: opt_compatible = True
        
        if opt_compatible:
            valid_options.append(str(r_row['aspect_ratio']))

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
def process_single_item(row, target_ratio, sheet_name, model_name, use_ref, instruction, col_map, retry_settings):
    """
    雙引擎處理邏輯 + 顯示存檔路徑
    """
    try:
        item_id = str(row[col_map['ID']] if col_map['ID'] in row else 'Unknown').strip()
        prompt_text = str(row[col_map['Prompt']] if col_map['Prompt'] in row else '').strip()
    except:
        return {"error": "Column read error"}
    
    # 處理 Aspect Ratio 字串 (例如 09:16:00 -> 9:16)
    ar_val = str(target_ratio if target_ratio else '1:1').strip()
    
    # 嘗試清理不標準的 AR (例如包含秒數的 09:16:00)
    if ar_val.count(':') == 2:
        ar_val = ar_val.rsplit(':', 1)[0] # 去掉最後一個 :00
    if ar_val.startswith('0'):
        ar_val = ar_val[1:] # 去掉開頭的 0 (如 09:16 -> 9:16)
        
    ratio_name = ar_val.replace(':', 'x')
    
    final_prompt_text = f"{instruction}\n\nAspect Ratio: {ar_val}\nPrompt: {prompt_text}"

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
        is_imagen = 'imagen' in model_name.lower()
        
        # ==========================================
        # 🅰️ 路線 A: Imagen (Generate Images)
        # ==========================================
        if is_imagen:
            if image_bytes:
                return {"error": "Imagen model does not support Ref Image in this script. Switch to Gemini."}

            # 🔥 [修正] 移除 safety_settings (導致 Extra inputs not permitted 錯誤的原因)
            config_params = {
                'number_of_images': 1,
                'aspect_ratio': ar_val,
                'output_mime_type': "image/jpeg"
            }
            
            response = call_api_with_retry(
                global_client.models.generate_images, 
                model=model_name, 
                prompt=final_prompt_text, 
                config=config_params,
                retry_settings=retry_settings
            )
            
            if response.generated_images:
                img_result_data = response.generated_images[0].image.image_bytes
            else:
                return {"error": "Imagen returned no images"}

        # ==========================================
        # 🅱️ 路線 B: Gemini (Generate Content)
        # ==========================================
        else:
            parts = [types.Part.from_text(text=final_prompt_text)]
            if image_bytes:
                parts.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))

            gen_config = types.GenerateContentConfig(
                response_modalities=["IMAGE"],
            )

            response = call_api_with_retry(
                global_client.models.generate_content,
                model=model_name,
                contents=[types.Content(role="user", parts=parts)],
                config=gen_config,
                retry_settings=retry_settings
            )

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
        # 🏁 存檔
        # ==========================================
        if img_result_data:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            clean_sheet = re.sub(r'[\\/*?:"<>|]', "", str(sheet_name))
            clean_id = re.sub(r'[\\/*?:"<>|]', "", str(item_id))
            
            filename = f"{clean_sheet}_{clean_id}_{ratio_name}_{timestamp}.png"
            save_path = os.path.join(OUTPUT_FOLDER, filename)
            
            with open(save_path, "wb") as f:
                f.write(img_result_data)
            
            return {"status": "Success", "path": save_path}
        else:
            return {"error": "Unknown error: No data extracted"}

    except Exception as e:
        return {"error": str(e)}

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
        "ratios_df": pd.DataFrame()
    }
    
    if not os.path.exists(config_path): 
        log(f"⚠️ Config file not found at {config_path}. Using defaults.")
        return settings

    try:
        # 1. Model Config
        try:
            df = pd.read_excel(config_path, sheet_name='Model_Config')
            df = normalize_cols(df)
            
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

def configure_runtime_settings(initial_model_name):
    print("\n" + "="*30 + "\n   🛠️  RUNTIME SETTINGS\n" + "="*30)
    
    t_in = input("👉 Run single test mode? (Y/N) [default: Y]: ").strip().upper()
    test_single = False if t_in == 'N' else True
    
    r_in = input("👉 Do you want to upload a reference image? (Y/N) [default: N]: ").strip().upper()
    use_ref = True if r_in == 'Y' else False

    final_model = initial_model_name
    
    if use_ref:
        name_lower = final_model.lower()
        is_valid_img2img = ('gemini' in name_lower) and ('image' in name_lower)
        if not is_valid_img2img:
            print(f"⚠️  Model '{final_model}' does not support Image-to-Image.")
            final_model = 'gemini-2.5-flash-image'
            print(f"🔄  Forced switch to: {final_model}")
        else:
            print(f"✅  Reference Image Mode ON. Using: {final_model}")
    else:
        print(f"✅  Model selected: {final_model}")

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

        CONFIG_PATH = os.path.join(BASE_DIR, "Config_Data.xlsx")
        log(f"⏳ Loading base settings from: {os.path.basename(CONFIG_PATH)}...")
        settings = load_settings(CONFIG_PATH)
        
        test_single, use_ref_image, target_model = configure_runtime_settings(settings["model_name"])

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
                    
                    # 🔥 傳入 retry_settings
                    jobs.append((row, validated_ratio, sheet, target_model, use_ref_image, instruction_content, col_map, settings["retry_settings"]))
                    if test_single: break
                
                if not jobs:
                    log("     ℹ️  No valid jobs.")
                    continue

                log(f"     🔥 Starting {len(jobs)} tasks (Max Workers: {settings['max_workers']})...")
                
                # 🔥 使用 Config 讀取的 Max Workers
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
            
            if test_single: 
                print("\n🛑 Test mode: Stopping after first file.")
                break

    except Exception as e:
        log(f"\n❌ Fatal Error: {e}")
        import traceback
        traceback.print_exc()
    
    input("\n✅ Execution finished. Press Enter to exit...")