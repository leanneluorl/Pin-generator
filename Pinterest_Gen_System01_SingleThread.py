print("🚀 System initializing... Please wait while libraries are loading.")
import sys
import os
import re
import time
import warnings
import random
import logging
import threading
from datetime import datetime
from dotenv import dotenv_values
from PIL import Image
import pandas as pd
from google import genai
from google.genai.errors import APIError
from jinja2 import Template
import multiprocessing

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
LOG_FILE_PATH = os.path.join(LOG_FOLDER, f"log-{current_time_str}.txt")

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
log(f"🚀 Pinterest Content Generator (Single-Threaded Safe Mode)")
log(f"📂 Working Directory: {BASE_DIR}")
log(f"📝 Log file: {LOG_FILE_PATH}")
print("-" * 50)

# 設定其他檔案路徑
ENV_FILE_PATH = os.path.join(BASE_DIR, ".env")
CONFIG_FILE = os.path.join(BASE_DIR, "Pinterest_Affiliate_Data.xlsx")
PRODUCT_FILE = os.path.join(BASE_DIR, "Pinterest_Affiliate_Product.xlsx")
OUTPUT_FOLDER = os.path.join(BASE_DIR, "Generated_Content")
PRODUCT_IMAGE_FOLDER = os.path.join(BASE_DIR, "product_image")

IMAGE_PROMPT_TEMPLATE_FILE = os.path.join(BASE_DIR, "image_prompt_template.txt")
CONTENT_PROMPT_TEMPLATE_FILE = os.path.join(BASE_DIR, "content_prompt_template.txt")

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# 檢查必要檔案
missing_files = []
for path in [CONFIG_FILE, PRODUCT_FILE]:
    if not os.path.isfile(path):
        missing_files.append(os.path.basename(path))

if missing_files:
    log(f"\n❌ Critical Error: Missing required files in {BASE_DIR}:")
    for f in missing_files:
        log(f"   - {f}")
    input("Press Enter to exit...")
    sys.exit(1)

if not os.path.isdir(PRODUCT_IMAGE_FOLDER):
    log(f"⚠️ Image folder not found: {PRODUCT_IMAGE_FOLDER}. Products without images will be skipped.")

# ------------------- Interactive settings -------------------
log("\n--- Configuration Setup ---")
test_single_input = input("Run single test mode? (Y/N): ").strip().lower()
test_single = test_single_input == 'y'

require_affiliate_input = input("Is 'Affiliate_Link' a required field? (Y/N): ").strip().lower()
require_affiliate_link = require_affiliate_input == 'y'

BASE_REQUIRED_COLS = ['Product_ID', 'Product_Name', 'Image_name', 'Product_desc']
REQUIRED_PRODUCT_COLS = BASE_REQUIRED_COLS.copy()

if require_affiliate_link:
    REQUIRED_PRODUCT_COLS.append('Affiliate_Link')

# ------------------- API Setup -------------------
log("\n--- Loading API key ---")
env_config = dotenv_values(ENV_FILE_PATH)
GEMINI_API_KEY = env_config.get("GEMINI_API_KEY")

use_mock = False
global_client = None 

if not GEMINI_API_KEY:
    log(f"⚠️ GEMINI_API_KEY not detected.")
    use_mock = input("   Use simulation mode? (Y/N): ").strip().lower() == 'y'
    if not use_mock:
        sys.exit()
else:
    if not use_mock:
        try:
            # 🔥 保持全域 Client 優化，避免重複連線
            global_client = genai.Client(api_key=GEMINI_API_KEY)
            log("✓ Global Gemini Client initialized.")
        except Exception as e:
            log(f"❌ Failed to initialize Client: {e}")
            sys.exit(1)

# ------------------- Helper functions -------------------
title_lock = threading.Lock()

def extract_clean_text(response):
    try:
        if hasattr(response, "text") and response.text:
            return response.text.strip()
        if hasattr(response, "candidates") and response.candidates:
            parts = response.candidates[0].content.parts
            text_parts = [p.text for p in parts if hasattr(p, "text")]
            return "\n".join(text_parts).strip()
        return str(response)
    except Exception:
        return "[ERROR: Unable to extract text]"

def ensure_template_exists(path, default_text):
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(default_text.strip())

def load_template(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def render_template(template_str):
    return Template(template_str).render()

def resize_image_for_api(image_path, max_length=1024):
    """讀取並縮小圖片以加快上傳與處理"""
    try:
        img = Image.open(image_path)
        if max(img.size) > max_length:
            ratio = max_length / max(img.size)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        return img
    except Exception as e:
        raise Exception(f"Failed to resize image: {e}")

def load_config_and_styles(config_file):
    try:
        df_model = pd.read_excel(config_file, sheet_name='Model_Config')
        df_model.columns = df_model.columns.str.strip() 

        def is_selected(val):
            s = str(val).strip().lower()
            return s in ['true', '1', 'yes', '1.0', 'y', 'on']

        selected_model_series = df_model[df_model['Selection'].apply(is_selected)]
        
        selected_model = "gemini-2.0-flash-lite" # 預設改為更穩定的 Lite
        delay_seconds = 0.0

        if selected_model_series.empty:
            log(f"⚠️ No model selected. Defaulting to '{selected_model}'")
        else:
            if len(selected_model_series) > 1:
                log("⚠️ Multiple models selected. Using the first one.")

            row = selected_model_series.iloc[0]
            selected_model = str(row['Model_Name']).strip()
            
            if 'Rate_Limit_Delay' in row and pd.notna(row['Rate_Limit_Delay']):
                try:
                    delay_seconds = float(row['Rate_Limit_Delay'])
                except ValueError:
                    delay_seconds = 0.0

        df_style = pd.read_excel(config_file, sheet_name='Styles_Config', engine='openpyxl').fillna('')
        df_style.columns = df_style.columns.str.strip()
        df_style.set_index('Style_ID', inplace=True)
        
        df_process = pd.read_excel(config_file, sheet_name='Process_Config', engine='openpyxl')
        process_sheets = df_process['Product_Sheet_Name'].dropna().astype(str).tolist()

        log(f"✓ Selected Model: {selected_model}")
        log(f"✓ Execution Mode: Single-Threaded (Sequential)")
        log(f"✓ Configured Delay: {delay_seconds} seconds")
        log(f"✓ Sheets to process: {process_sheets}")

        return selected_model, df_style, process_sheets, delay_seconds
    except Exception as e:
        log(f"✗ Config Error: {e}")
        return None, None, None, 0

def parse_text_output(text):
    data = {'Pin_Title': "ERROR", 'Pin_Description': "ERROR", 'Pin_Hashtags': "ERROR"}
    if not text: return data
    cleaned = text.strip()
    patterns = {
        'Pin_Title': re.search(r'(?:\[|\*\*|^)?\s*title\s*(?:\]|\*\*|:)?\s*[:：\-]?\s*(.+?)(?=\n(?:\[|\*\*|^)?\s*description|\n(?:\[|\*\*|^)?\s*hashtags|$)', cleaned, re.IGNORECASE | re.DOTALL),
        'Pin_Description': re.search(r'(?:\[|\*\*|^)?\s*description\s*(?:\]|\*\*|:)?\s*[:：\-]?\s*(.+?)(?=\n(?:\[|\*\*|^)?\s*hashtags|$)', cleaned, re.IGNORECASE | re.DOTALL),
        'Pin_Hashtags': re.search(r'(?:\[|\*\*|^)?\s*hashtags?\s*(?:\]|\*\*|:)?\s*[:：\-]?\s*(.+)', cleaned, re.IGNORECASE | re.DOTALL)
    }
    for key, match in patterns.items():
        if match:
            val = match.group(1).strip()
            val = re.sub(r'\*\*$', '', val)
            data[key] = val
    if "ERROR" in data['Pin_Hashtags']:
        hashtags = re.findall(r'#\w+', cleaned)
        if hashtags: data['Pin_Hashtags'] = ' '.join(hashtags)
    return data

# --- LOAD CONFIGURATION ---
default_image_prompt = "Create a detailed visual prompt for Pinterest-style imagery."
default_content_prompt = "Write engaging Pinterest content."
ensure_template_exists(IMAGE_PROMPT_TEMPLATE_FILE, default_image_prompt)
ensure_template_exists(CONTENT_PROMPT_TEMPLATE_FILE, default_content_prompt)

log("\n⏳ Loading configuration and styles from Excel...")
config_result = load_config_and_styles(CONFIG_FILE)
if config_result[0] is None: sys.exit()

selected_model, df_style, process_sheets, config_delay = config_result

image_prompt_template = load_template(IMAGE_PROMPT_TEMPLATE_FILE)
content_prompt_template = load_template(CONTENT_PROMPT_TEMPLATE_FILE)

current_datetime = datetime.now().strftime("%Y%m%d%H%M")
output_path_generated = os.path.join(OUTPUT_FOLDER, f"Generated_Content_{current_datetime}.xlsx")
output_path_input_errors = os.path.join(BASE_DIR, f"Input_Errors_{current_datetime}.xlsx")

all_sheet_results = {}
input_error_list = []
generation_error_list = []
used_titles = set()

log("\n⏳ Loading product data...")
try:
    product_excel_file = pd.ExcelFile(PRODUCT_FILE)
    actual_product_sheets = product_excel_file.sheet_names
except Exception as e:
    log(f"❌ Error reading product file: {e}")
    sys.exit()

# ------------------- Auto-Retry API Wrapper -------------------
def call_api_with_retry(api_func, *args, max_retries=5, **kwargs):
    """
    精準控制重試邏輯
    """
    attempt = 0
    base_wait = 10 
    
    while attempt <= max_retries:
        try:
            return api_func(*args, **kwargs)
        
        except Exception as e:
            error_str = str(e).lower()
            
            # (A) 硬性額度限制：Limit: 0 
            if "limit: 0" in error_str or "limit=0" in error_str:
                log(f"❌ [FATAL] Quota is ZERO (Limit: 0). Stopping.")
                log(f"   👉 建議：請更換模型名稱 (例如改用 gemini-2.0-flash-lite)")
                raise e 

            # (B) 客戶端錯誤
            if any(code in error_str for code in ["400", "401", "403", "404"]):
                log(f"❌ [FATAL] Client Error ({error_str[:50]}...). Stopping.")
                raise e

            # (C) 值得重試的錯誤
            retry_keywords = [
                "429", "too many requests", "resource_exhausted", "quota", 
                "500", "502", "503", "504", "internal server error",       
                "service unavailable", "gateway timeout", "socket"         
            ]
            
            if any(k in error_str for k in retry_keywords):
                attempt += 1
                if attempt > max_retries:
                    log(f"❌ API Retry Failed after {max_retries} attempts.")
                    raise e
                
                wait_time = (base_wait * (2 ** (attempt - 1))) + random.uniform(1, 5)
                error_preview = "429 Too Many Requests" if "429" in error_str else "Server Error"
                log(f"⚠️ API Issue ({error_preview}). Waiting {wait_time:.1f}s... (Retry {attempt}/{max_retries})")
                time.sleep(wait_time)
            else:
                log(f"❌ Unexpected Error: {error_str[:200]}")
                raise e
            
# ------------------- Worker Function -------------------
def process_single_product(product_row, style_row, sheet_name):
    product_id = str(product_row.get('Product_ID', 'Unknown')).strip()
    product_name = str(product_row.get('Product_Name', 'Unknown')).strip()
    style_name = str(style_row.get('style_Name', 'Default')).strip()
    
    local_client = global_client
    
    error_context = {
        "Source_Product_Sheet": sheet_name,
        "Product_ID": product_id,
        "Product_Name": product_name,
        "Error_Message": "",
        "Raw_Response": ""
    }

    image_name = str(product_row.get('Image_name', '')).strip()
    image_path = os.path.join(PRODUCT_IMAGE_FOLDER, image_name)

    try:
        if not image_name or not os.path.isfile(image_path):
            raise FileNotFoundError(f"Image not found: {image_name}")
        product_image = resize_image_for_api(image_path)
    except Exception as e:
        error_context['Error_Message'] = f"Image Error: {str(e)}"
        return {"error": True, "details": error_context}

    product_info = (
        f"\n--- Product Information ---\n"
        f"Product: {product_name}\n"
        f"Description: {product_row.get('Product_desc', '')}\n"
        f"Category: {product_row.get('Category', '')}\n"
        f"Style: {style_name}\n"
        f"Keywords: {product_row.get('Base_Keywords', '')}\n"
        f"Mood: {style_row.get('Mood_Descriptor', '')}\n"
        f"Call to Action: {product_row.get('Call_To_Action', '')}\n"
    )

    format_instructions = (
        "\n\nIMPORTANT: You must format your response exactly as follows:\n"
        "[Title]: (Your catchy title here)\n"
        "[Description]: (Your description here)\n"
        "[Hashtags]: (Your hashtags here)\n"
    )

    img_prompt_text = render_template(image_prompt_template) + "\n" + product_info
    content_prompt_text = render_template(content_prompt_template) + "\n" + product_info + format_instructions

    final_img_prompt = ""
    parsed_output = {}

    if use_mock:
        final_img_prompt = "Simulated Prompt"
        parsed_output = {'Pin_Title': f"Mock Title {product_id}", 'Pin_Description': "Mock Desc", 'Pin_Hashtags': "#Mock"}
    else:
        try:
            # 1. 產生圖片 Prompt
            resp_img = call_api_with_retry(
                local_client.models.generate_content,
                model=selected_model,
                contents=[product_image, img_prompt_text]
            )
            final_img_prompt = extract_clean_text(resp_img)

            # 2. 產生文案
            resp_text = call_api_with_retry(
                local_client.models.generate_content,
                model=selected_model,
                contents=[product_image, content_prompt_text]
            )
            raw_api_response = extract_clean_text(resp_text)
            
            parsed_output = parse_text_output(raw_api_response)
            
            if "ERROR:" in parsed_output['Pin_Title']:
                error_context['Error_Message'] = "Parsing Error"
                error_context['Raw_Response'] = raw_api_response
                return {"error": True, "details": error_context}

            # 3. 標題去重
            raw_title = parsed_output['Pin_Title'].strip()
            normalized_title = re.sub(r'\W+', '', raw_title.lower())
            
            need_retry = False
            with title_lock: # 單線程其實不需要 Lock，但保留無妨
                if normalized_title in used_titles: need_retry = True
            
            if need_retry:
                regen_prompt = f"Regenerate unique Pinterest [Title]. Do not use: {raw_title}\nFormat: [Title]: New Title"
                try:
                    resp_retry = call_api_with_retry(
                        local_client.models.generate_content,
                        model=selected_model,
                        contents=[product_image, regen_prompt]
                    )
                    new_data = parse_text_output(extract_clean_text(resp_retry))
                    if "ERROR" not in new_data['Pin_Title']:
                        raw_title = new_data['Pin_Title']
                        normalized_title = re.sub(r'\W+', '', raw_title.lower())
                except: pass
            
            used_titles.add(normalized_title)
            parsed_output['Pin_Title'] = raw_title

        except Exception as e:
            error_context['Error_Message'] = f"API Error: {str(e)}"
            return {"error": True, "details": error_context}

    raw_hashtags = parsed_output.get('Pin_Hashtags', '')
    keywords_list = re.findall(r'#(\w+)', raw_hashtags)
    pin_keywords = ', '.join(keywords_list)

    return {
        'Pin_Name_For_Upload': f"{product_id}_{style_row['style_Name']}".replace(' ','_'),
        'Affiliate_Link': product_row.get('Affiliate_Link', ''),
        'Image_name': image_name,
        'Image_Prompt_For_AI': final_img_prompt,
        'Pin_Title': parsed_output['Pin_Title'],
        'Pin_Description': parsed_output['Pin_Description'],
        'Pin_Keywords': pin_keywords,
        'Generated_Date': current_datetime,
        'Source_Product_Sheet': sheet_name,
        'Product_ID': product_id,
        'Applied_Style_ID': style_row.name,
        'Style_Name': style_row['style_Name']
    }

# =======================================================
# 🔥 Main Execution (單線程版 + 主動等待)
# =======================================================
if __name__ == '__main__':
    multiprocessing.freeze_support()

    log(f"\n⚙ Starting execution (Sequential Processing with Throttling).")
    
    try:
        for sheet_name in process_sheets:
            if sheet_name not in actual_product_sheets: continue
            log(f"\n--- Processing: {sheet_name} ---")

            df_products = pd.read_excel(PRODUCT_FILE, sheet_name=sheet_name, engine='openpyxl').fillna('')
            if 'Pinterest_Angle' in df_products.columns:
                df_products.rename(columns={'Pinterest_Angle':'Product_desc'}, inplace=True)

            # 建立任務清單
            job_list = []
            for idx, product_row in df_products.iterrows():
                product_id = str(product_row.get('Product_ID', 'N/A'))
                
                missing_cols = [col for col in REQUIRED_PRODUCT_COLS if col not in df_products.columns or pd.isna(product_row[col]) or str(product_row[col]).strip() == '']
                if missing_cols:
                    input_error_list.append({'Source_Product_Sheet': sheet_name, 'Product_ID': product_id, 'Error_Message': f"Missing: {missing_cols}"})
                    continue

                img_name = str(product_row.get('Image_name', '')).strip()
                if not os.path.isfile(os.path.join(PRODUCT_IMAGE_FOLDER, img_name)):
                    input_error_list.append({'Source_Product_Sheet': sheet_name, 'Product_ID': product_id, 'Error_Message': f"Missing Image: {img_name}"})
                    continue 

                for style_id, style_row in df_style.iterrows():
                    job_list.append((product_row, style_row, sheet_name))
                    if test_single: break
                if test_single: break

            # 🔥 [核心修改] 加入主動等待 (Throttling)
            results = []
            total_jobs = len(job_list)
            
            for i, (prod_row, sty_row, sht_name) in enumerate(job_list):
                try:
                    # 顯示當前進度
                    pid = str(prod_row.get('Product_ID', 'N/A'))
                    sty = sty_row['style_Name']
                    print(f"   [Processing {i+1}/{total_jobs}] {pid} - {sty} ... ", end="", flush=True)
                    
                    # 執行處理
                    result = process_single_product(prod_row, sty_row, sht_name)
                    results.append(result)
                    
                    if result.get('error'):
                        print("❌ Failed")
                    else:
                        print("✅ Done")
                    
                    # 🛑 [主動等待機制] 避免跑太快撞到 429
                    # 如果不是最後一筆，就強制休息 5~10 秒
                    if i < total_jobs - 1:
                        # 隨機等待 5 到 10 秒
                        wait_time = random.uniform(5, 10)
                        
                        # 顯示倒數計時，讓你知道程式沒當機
                        print(f"      ⏳ Cooling down... waiting {wait_time:.1f}s to avoid Rate Limit")
                        time.sleep(wait_time)

                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    print(f"❌ Error: {e}")
                    results.append({"error": True, "details": {"Source_Product_Sheet": sht_name, "Error_Message": str(e)}})
                    # 發生未知錯誤也要休息一下
                    time.sleep(5)

            success_data = [r for r in results if isinstance(r, dict) and not r.get('error')]
            error_data = [r['details'] for r in results if isinstance(r, dict) and r.get('error')]

            if success_data:
                df = pd.DataFrame(success_data)
                cols = ['Pin_Name_For_Upload', 'Affiliate_Link', 'Image_name', 'Image_Prompt_For_AI', 'Pin_Title', 'Pin_Description', 'Pin_Keywords', 'Generated_Date', 'Source_Product_Sheet', 'Product_ID', 'Applied_Style_ID', 'Style_Name']
                all_sheet_results[sheet_name] = df[[c for c in cols if c in df.columns]]
            
            if error_data: generation_error_list.extend(error_data)

    except KeyboardInterrupt:
        log("\n🛑 Interrupted! Saving data...")
    except Exception as e:
        log(f"\n❌ Critical Error: {e}")
    finally:
        log("\n--- Saving Results ---")
        if all_sheet_results:
            with pd.ExcelWriter(output_path_generated, engine='openpyxl') as writer:
                for sheet, df in all_sheet_results.items(): df.to_excel(writer, sheet_name=sheet, index=False)
            log(f"✓ Results: {output_path_generated}")

        all_errors = input_error_list + generation_error_list
        if all_errors:
            pd.DataFrame(all_errors).to_excel(output_path_input_errors, index=False)
            log(f"⚠ Errors: {output_path_input_errors}")
        
        log(f"📝 Log: {LOG_FILE_PATH}")
        if getattr(sys, 'frozen', False): input("Press Enter to exit...")