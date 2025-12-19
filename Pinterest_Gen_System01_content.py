print("🚀 System initializing... Please wait while libraries are loading.")
import sys
import os
import re
import time
import warnings
import random
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from dotenv import dotenv_values
from PIL import Image
import pandas as pd
from google import genai
from google.genai.errors import APIError
from jinja2 import Template
import multiprocessing
import shutil  # ⚠️ 記得確保有這行 import

# 忽略 pandas 的 FutureWarning
warnings.filterwarnings("ignore")


# =======================================================
# 🛠️ 自動釋放資源函式 (Self-Extracting Logic)
# =======================================================
def check_and_release_assets(base_dir):
    """
    EXE 啟動時檢查：
    如果外部沒有設定檔，就從 EXE 內部 (sys._MEIPASS) 複製一份出來。
    """
    # 這是 PyInstaller 打包後的內部暫存路徑
    if hasattr(sys, "_MEIPASS"):
        internal_path = sys._MEIPASS
    else:
        # 如果是跑原始碼 .py，來源就是當前目錄
        internal_path = base_dir

    # 定義要檢查並釋放的檔案 (檔名必須與 build.py 打包時的目標名稱一致)
    files_to_check = [
        "Config_Data.xlsx",
        "Pinterest_Affiliate_Product.xlsx",
        "image_prompt_template.txt",
        "content_prompt_template.txt",
        ".env",  # 如果有需要的話
    ]

    print("\n🔍 System Integrity Check (Auto-Release)...")

    for filename in files_to_check:
        target_file = os.path.join(base_dir, filename)
        source_file = os.path.join(internal_path, filename)

        # 1. 檢查外部檔案是否存在
        if not os.path.exists(target_file):
            # 2. 外部沒有，嘗試從內部複製
            if os.path.exists(source_file):
                try:
                    shutil.copy2(source_file, target_file)
                    print(f"   🆕 Missing file created: {filename}")
                except Exception as e:
                    print(f"   ❌ Failed to create {filename}: {e}")
            else:
                # 內部也沒有 (可能是開發環境沒放 sample)
                print(f"   ⚠️ Internal source missing: {filename}")
        else:
            # 外部已有檔案，不做事 (避免覆蓋使用者的設定)
            pass


# =======================================================
# 📂 核心路徑與 Log 設定
# =======================================================
def get_base_path():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = get_base_path()


# =======================================================
# 🛠️ [新增功能] 自動釋放打包資源
# =======================================================
def get_internal_path(filename):
    """取得打包在 EXE 內部的資源路徑"""
    if hasattr(sys, "_MEIPASS"):
        # PyInstaller 打包後的內部暫存路徑
        return os.path.join(sys._MEIPASS, filename)
    else:
        # 開發模式下，直接抓腳本旁邊的檔案
        return os.path.join(BASE_DIR, filename)


def release_initial_files():
    """如果外部檔案不存在，則從 EXE 內部釋放出來"""

    # 🔥 修正：加入 ".env" 到釋放清單
    assets_to_release = [
        "Config_Data.xlsx",
        "Pinterest_Affiliate_Product.xlsx",
        "image_prompt_template.txt",
        "content_prompt_template.txt",
        ".env",
    ]

    log("🔍 Checking for essential files...")

    # 取得目前目錄檔案列表 (用於 Config 判斷)
    try:
        current_files_in_dir = os.listdir(BASE_DIR)
    except Exception as e:
        log(f"⚠️ Error reading directory: {e}")
        current_files_in_dir = []

    for filename in assets_to_release:
        target_path = os.path.join(BASE_DIR, filename)
        need_to_copy = True

        # 1. Config 檔特殊檢查：如果有任何 Config_Data*.xlsx 就不生成
        if filename == "Config_Data.xlsx":
            existing_configs = [
                f
                for f in current_files_in_dir
                if f.lower().startswith("config_data") and f.lower().endswith(".xlsx")
            ]
            if existing_configs:
                log(
                    f"   ✅ Found existing config(s): {existing_configs}. Skipping default generation."
                )
                need_to_copy = False

        # 2. 標準檢查：如果檔案已存在 (例如 .env 已經有 Key 了)，絕對不覆蓋
        if os.path.exists(target_path):
            need_to_copy = False

        # 3. 執行釋放
        if need_to_copy:
            internal_source = get_internal_path(filename)
            if os.path.exists(internal_source):
                try:
                    shutil.copy2(internal_source, target_path)
                    log(f"📦 Auto-generated missing file: {filename}")
                except Exception as e:
                    log(f"⚠️ Failed to release {filename}: {e}")
            else:
                # 只有開發模式下可能會找不到內部資源
                pass


# 設定 Log 資料夾與檔案
LOG_FOLDER = os.path.join(BASE_DIR, "Logs")
os.makedirs(LOG_FOLDER, exist_ok=True)
current_time_str = datetime.now().strftime("%Y%m%d-%H%M%S")
LOG_FILE_PATH = os.path.join(LOG_FOLDER, f"log-{current_time_str}.txt")

# 🔥 設定 Logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)


def log(msg):
    logging.info(msg)


# 🔥 啟動畫面
print("-" * 50)
log(f"🚀 Pinterest Content Generator (Optimized Batch Mode)")
log(f"📂 Working Directory: {BASE_DIR}")
log(f"📝 Log file: {LOG_FILE_PATH}")
print("-" * 50)

release_initial_files()

# 設定其他檔案路徑
ENV_FILE_PATH = os.path.join(BASE_DIR, ".env")
PRODUCT_FILE = os.path.join(BASE_DIR, "Pinterest_Affiliate_Product.xlsx")
OUTPUT_FOLDER = os.path.join(BASE_DIR, "Generated_Content")
REF_IMAGE_FOLDER = os.path.join(BASE_DIR, "ref_image")

IMAGE_PROMPT_TEMPLATE_FILE = os.path.join(BASE_DIR, "image_prompt_template.txt")
CONTENT_PROMPT_TEMPLATE_FILE = os.path.join(BASE_DIR, "content_prompt_template.txt")

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# =======================================================
# 📂 Config 檔案選取邏輯
# =======================================================
CONFIG_FILE = None

while CONFIG_FILE is None:
    log("\n🔍 Scanning for Config files...")
    config_candidates = [
        f
        for f in os.listdir(BASE_DIR)
        if f.lower().startswith("config_data") and f.lower().endswith(".xlsx")
    ]
    options = config_candidates.copy()
    manual_option_idx = len(options) + 1

    print("\n" + "=" * 30)
    print("   SELECT CONFIGURATION FILE")
    print("=" * 30)

    if not options:
        log("⚠️ No auto-detected 'Config_Data*.xlsx' files found.")
    else:
        for idx, f in enumerate(options):
            print(f"  [{idx + 1}] {f}")

    print(f"  [{manual_option_idx}] 📝 Enter file path manually")
    print("-" * 30)

    user_input = input(f"👉 Select an option (1-{manual_option_idx}): ").strip()
    selected_temp_path = ""

    if user_input.isdigit():
        idx = int(user_input)
        if 1 <= idx <= len(options):
            selected_temp_path = os.path.join(BASE_DIR, options[idx - 1])
        elif idx == manual_option_idx:
            manual_input = input(
                "👉 Please enter the file name (e.g., MyConfig.xlsx): "
            ).strip()
            manual_input = manual_input.replace('"', "").replace("'", "")
            if os.path.isabs(manual_input):
                selected_temp_path = manual_input
            else:
                selected_temp_path = os.path.join(BASE_DIR, manual_input)
        else:
            log("❌ Invalid number. Please try again.")
            continue
    else:
        log("❌ Please enter a valid number.")
        continue

    if os.path.isfile(selected_temp_path):
        CONFIG_FILE = selected_temp_path
        log(f"✅ Successfully loaded: {CONFIG_FILE}")
    else:
        log(f"❌ File not found: {selected_temp_path}")
        print("   Please check the file name and try again.\n")

if not os.path.isfile(PRODUCT_FILE):
    log(f"\n❌ Critical Error: Missing product file: {PRODUCT_FILE}")
    input("Press Enter to exit...")
    sys.exit(1)

# =======================================================
# 📂 [NEW] 圖片資料夾檢查與自動建立機制
# =======================================================
if not os.path.isdir(REF_IMAGE_FOLDER):
    print(f"\n[SYSTEM] ⚠️  Image folder 'ref_image' is missing.")
    print(f"   [1] Enter the name of your existing image folder (e.g., 'my_photos')")
    print(f"   [2] Create default 'ref_image' folder automatically")

    folder_choice = input("👉 Select option (1 or 2) [default=2]: ").strip()

    if folder_choice == "1":
        # 選項 1: 使用者自訂資料夾
        custom_name = input("👉 Enter your folder name: ").strip()
        # 移除可能的引號
        custom_name = custom_name.replace("'", "").replace('"', "")
        custom_path = os.path.join(BASE_DIR, custom_name)

        if os.path.isdir(custom_path):
            REF_IMAGE_FOLDER = custom_path
            log(f"✅ Using custom image folder: {REF_IMAGE_FOLDER}")
        else:
            # 防呆: 如果自訂的也找不到，強制建立預設資料夾
            log(
                f"❌ Folder '{custom_name}' not found. Automatically creating default 'ref_image'..."
            )
            os.makedirs(REF_IMAGE_FOLDER, exist_ok=True)
            print(f"📁 Created: {REF_IMAGE_FOLDER}")
            print(
                f"⚠️  Please put your product images in '{REF_IMAGE_FOLDER}' and run again if needed."
            )
    else:
        # 選項 2 (預設): 自動建立 ref_image
        log(f"📁 Auto-creating missing folder: {REF_IMAGE_FOLDER}")
        os.makedirs(REF_IMAGE_FOLDER, exist_ok=True)
        print(
            f"⚠️  Folder created. Please put your product images in 'ref_image' before running."
        )
else:
    # 資料夾存在
    log(f"✅ Image folder found: {REF_IMAGE_FOLDER}")

# ------------------- Interactive settings -------------------
log("\n--- Configuration Setup ---")
test_single_input = input("Run single test mode? (Y/N): ").strip().lower()
test_single = test_single_input == "y"

require_affiliate_input = (
    input("Is 'Affiliate_Link' a required field? (Y/N): ").strip().lower()
)
require_affiliate_link = require_affiliate_input == "y"

BASE_REQUIRED_COLS = ["Product_ID", "Product_Name", "Image_name", "Product_desc"]
REQUIRED_PRODUCT_COLS = BASE_REQUIRED_COLS.copy()
if require_affiliate_link:
    REQUIRED_PRODUCT_COLS.append("Affiliate_Link")

# ------------------- API Setup -------------------
log("\n--- Loading API key ---")
env_config = dotenv_values(ENV_FILE_PATH)
GEMINI_API_KEY = env_config.get("GEMINI_API_KEY")

use_mock = False
global_client = None

if not GEMINI_API_KEY:
    log(f"⚠️ GEMINI_API_KEY not detected.")
    use_mock = input("   Use simulation mode? (Y/N): ").strip().lower() == "y"
    if not use_mock:
        sys.exit()
else:
    if not use_mock:
        try:
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
    try:
        img = Image.open(image_path)
        if max(img.size) > max_length:
            ratio = max_length / max(img.size)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        return img
    except Exception as e:
        raise Exception(f"Failed to resize image: {e}")


def normalize_cols(df):
    df.columns = df.columns.str.strip().str.lower()
    return df


def load_config_and_styles(config_file):
    try:
        # 1. 讀取 Model Config
        df_model = pd.read_excel(config_file, sheet_name="Model_Config")
        df_model = normalize_cols(
            df_model
        )  # 轉小寫: model_name, selection, model_type...

        def is_selected(val):
            s = str(val).strip().lower()
            return s in ["true", "1", "yes", "1.0", "y", "on"]

        # 找出被勾選的模型
        selected_model_series = df_model[df_model["selection"].apply(is_selected)]

        # 設定預設安全模型
        default_model = "gemini-2.0-flash"
        selected_model = default_model

        if selected_model_series.empty:
            log(f"⚠️ No model selected. Defaulting to '{default_model}'")
        else:
            if len(selected_model_series) > 1:
                log("⚠️ Multiple models selected. Using the first one.")

            row = selected_model_series.iloc[0]
            candidate_model = str(row.get("model_name", default_model)).strip()
            # 取得 Model Type 並轉小寫比對 (容錯處理)
            model_type = str(row.get("model_type", "unknown")).strip().lower()

            # 🔥 [核心修正] 強制檢查 Model_Type 是否為 Text
            # 只有標註為 "Text" 的模型才支援圖轉文 (Multimodal)
            if model_type == "text":
                selected_model = candidate_model
                log(
                    f"✓ Selected Model: {selected_model} (Type: {row.get('model_type', 'Text')})"
                )
            else:
                log(
                    f"\n⚠️  Warning: You selected '{candidate_model}' which is a '{row.get('model_type', 'Unknown')}' model."
                )
                log(
                    f"    This Content Generator requires a 'Text' type model (Multimodal)."
                )
                log(
                    f"🔄  Safety Fallback: Switching to default '{default_model}' to prevent errors.\n"
                )
                selected_model = default_model

        # 2. 讀取 Concurrency Config
        max_workers = 1

        try:
            df_concurrency = pd.read_excel(config_file, sheet_name="Concurrency_Config")
            df_concurrency = normalize_cols(df_concurrency)
            concurrency_dict = dict(
                zip(
                    df_concurrency["parameter"].astype(str).str.upper(),
                    df_concurrency["value"],
                )
            )
            if "MAX_WORKERS" in concurrency_dict:
                try:
                    max_workers = int(float(concurrency_dict["MAX_WORKERS"]))
                except:
                    log("⚠️ Invalid MAX_WORKERS in Concurrency_Config, using default 1")
        except Exception as e:
            log(f"⚠️ Could not load Concurrency_Config ({e}), using defaults.")

        # 3. 讀取 Styles Config
        df_style = pd.read_excel(
            config_file, sheet_name="Styles_Config", engine="openpyxl"
        ).fillna("")
        df_style = normalize_cols(df_style)
        df_style = df_style[df_style["selection"].apply(is_selected)]
        if "style_id" in df_style.columns:
            df_style.set_index("style_id", inplace=True)

        # 4. 讀取 Process Config
        df_process = pd.read_excel(
            config_file, sheet_name="Process_Config", engine="openpyxl"
        )

        # Sheet Deduplication
        raw_sheets = df_process.iloc[:, 0].dropna().astype(str).tolist()
        unique_process_sheets = list(dict.fromkeys([s.strip() for s in raw_sheets]))

        log(f"✓ Configured Workers: {max_workers}")
        log(f"✓ Sheets to process (Config List): {unique_process_sheets}")
        log(f"✓ Active Styles: {len(df_style)}")

        return selected_model, df_style, unique_process_sheets, max_workers, 0
    except Exception as e:
        log(f"✗ Config Error: {e}")
        return None, None, None, 1, 0


def parse_text_output(text):
    data = {"Pin_Title": "ERROR", "Pin_Description": "ERROR", "Pin_Hashtags": "ERROR"}
    if not text:
        return data
    cleaned = text.strip()
    patterns = {
        "Pin_Title": re.search(
            r"(?:\[|\*\*|^)?\s*title\s*(?:\]|\*\*|:)?\s*[:：\-]?\s*(.+?)(?=\n(?:\[|\*\*|^)?\s*description|\n(?:\[|\*\*|^)?\s*hashtags|$)",
            cleaned,
            re.IGNORECASE | re.DOTALL,
        ),
        "Pin_Description": re.search(
            r"(?:\[|\*\*|^)?\s*description\s*(?:\]|\*\*|:)?\s*[:：\-]?\s*(.+?)(?=\n(?:\[|\*\*|^)?\s*hashtags|$)",
            cleaned,
            re.IGNORECASE | re.DOTALL,
        ),
        "Pin_Hashtags": re.search(
            r"(?:\[|\*\*|^)?\s*hashtags?\s*(?:\]|\*\*|:)?\s*[:：\-]?\s*(.+)",
            cleaned,
            re.IGNORECASE | re.DOTALL,
        ),
    }
    for key, match in patterns.items():
        if match:
            val = match.group(1).strip()
            val = re.sub(r"\*\*$", "", val)
            data[key] = val
    if "ERROR" in data["Pin_Hashtags"]:
        hashtags = re.findall(r"#\w+", cleaned)
        if hashtags:
            data["Pin_Hashtags"] = " ".join(hashtags)
    return data


# --- LOAD CONFIGURATION ---
default_image_prompt = "Create a detailed visual prompt for Pinterest-style imagery."
default_content_prompt = "Write engaging Pinterest content."
ensure_template_exists(IMAGE_PROMPT_TEMPLATE_FILE, default_image_prompt)
ensure_template_exists(CONTENT_PROMPT_TEMPLATE_FILE, default_content_prompt)

log("\n⏳ Loading configuration and styles from Excel...")
config_result = load_config_and_styles(CONFIG_FILE)
if config_result[0] is None:
    input("Configuration failed. Press Enter to exit...")
    sys.exit()

selected_model, df_style, process_sheets, config_max_workers, config_delay = (
    config_result
)

image_prompt_template_content = load_template(IMAGE_PROMPT_TEMPLATE_FILE)
content_prompt_template_content = load_template(CONTENT_PROMPT_TEMPLATE_FILE)

current_datetime = datetime.now().strftime("%Y%m%d%H%M")
output_path_generated = os.path.join(
    OUTPUT_FOLDER, f"Generated_Content_{current_datetime}.xlsx"
)
output_path_input_errors = os.path.join(
    BASE_DIR, f"Input_Errors_{current_datetime}.xlsx"
)

all_sheet_results = {}
input_error_list = []
generation_error_list = []
used_titles = set()
processed_real_sheets = set()  # 用於防止 Sheet 重複處理

log("\n⏳ Loading product data...")
try:
    product_excel_file = pd.ExcelFile(PRODUCT_FILE)
    actual_product_sheets = product_excel_file.sheet_names
except Exception as e:
    log(f"❌ Error reading product file: {e}")
    input("Press Enter to exit...")
    sys.exit()


def call_api_with_retry(api_func, *args, max_retries=5, **kwargs):
    attempt = 0
    base_wait = 10
    while attempt <= max_retries:
        try:
            return api_func(*args, **kwargs)
        except Exception as e:
            error_str = str(e).lower()
            if "limit: 0" in error_str or "limit=0" in error_str:
                log(f"❌ [FATAL] Quota is ZERO (Limit: 0). Stopping.")
                raise e
            if any(code in error_str for code in ["400", "401", "403", "404"]):
                log(f"❌ [FATAL] Client Error ({error_str[:50]}...). Stopping.")
                raise e
            retry_keywords = ["429", "too many requests", "500", "502", "503", "504"]
            if any(k in error_str for k in retry_keywords):
                attempt += 1
                if attempt > max_retries:
                    raise e
                wait_time = (base_wait * (2 ** (attempt - 1))) + random.uniform(1, 5)
                time.sleep(wait_time)
            else:
                raise e


# ------------------- Worker Function -------------------
def process_single_product(product_row, style_row, sheet_name):
    product_id = str(product_row.get("Product_ID", "Unknown")).strip()
    product_name = str(product_row.get("Product_Name", "Unknown")).strip()
    style_name = str(
        style_row.get("style_name", style_row.get("Style_Name", "Default"))
    ).strip()

    local_client = global_client
    image_name = str(product_row.get("Image_name", "")).strip()
    image_path = os.path.join(REF_IMAGE_FOLDER, image_name)

    error_context = {
        "Source_Product_Sheet": sheet_name,
        "Product_ID": product_id,
        "Product_Name": product_name,
        "Error_Message": "",
        "Raw_Response": "",
    }

    try:
        ref_image = resize_image_for_api(image_path)
    except Exception as e:
        error_context["Error_Message"] = f"Image Processing Error: {str(e)}"
        return {"error": True, "details": error_context}

    mood_desc = style_row.get("mood_descriptor", style_row.get("style_description", ""))

    product_info = (
        f"\n--- Product Information ---\n"
        f"Product: {product_name}\n"
        f"Description: {product_row.get('Product_desc', '')}\n"
        f"Category: {product_row.get('Category', '')}\n"
        f"Style: {style_name}\n"
        f"Keywords: {product_row.get('Base_Keywords', '')}\n"
        f"Mood: {mood_desc}\n"
        f"Call to Action: {product_row.get('Call_To_Action', '')}\n"
    )

    combined_prompt = (
        f"You are a professional Pinterest Content Manager.\n"
        f"Analyze the attached image and the product details below:\n"
        f"{product_info}\n\n"
        f"Please generate 4 distinct outputs in a structured format:\n"
        f"1. A detailed text-to-image prompt for AI image generation (based on: {image_prompt_template_content})\n"
        f"2. A catchy Pinterest Pin Title\n"
        f"3. An engaging Pin Description (based on: {content_prompt_template_content})\n"
        f"4. Relevant Hashtags\n\n"
        f"⚠️ IMPORTANT: You must output the result strictly in this format (do not add intro text):\n"
        f"[Image Prompt]: (Write the detailed image prompt here)\n"
        f"[Title]: (Write the title here)\n"
        f"[Description]: (Write the description here)\n"
        f"[Hashtags]: (Write the hashtags here)\n"
    )

    final_img_prompt = ""
    parsed_output = {}

    if use_mock:
        final_img_prompt = "Simulated Prompt"
        parsed_output = {
            "Pin_Title": f"Mock Title {product_id}",
            "Pin_Description": "Mock Desc",
            "Pin_Hashtags": "#Mock",
        }
    else:
        try:
            resp = call_api_with_retry(
                local_client.models.generate_content,
                model=selected_model,
                contents=[ref_image, combined_prompt],
            )
            raw_response = extract_clean_text(resp)

            img_prompt_match = re.search(
                r"\[Image Prompt\]:?\s*(.+?)(?=\n\[Title\]|$)",
                raw_response,
                re.IGNORECASE | re.DOTALL,
            )
            final_img_prompt = (
                img_prompt_match.group(1).strip()
                if img_prompt_match
                else "Error parsing image prompt or not provided."
            )
            parsed_output = parse_text_output(raw_response)

            # =================================================
            # 🔥 [FIXED] 強健的防重複標題邏輯 (Thread-Safe Loop)
            # =================================================
            raw_title = parsed_output.get("Pin_Title", "Untitled")
            if "ERROR" in raw_title:
                raw_title = f"Untitled {product_id}"

            max_retries = 3  # 最大重試次數
            retry_count = 0
            title_is_unique = False

            while retry_count <= max_retries:
                # 1. 正規化標題
                normalized_title = re.sub(r"\W+", "", raw_title.lower())

                # 2. [關鍵修正] 檢查與佔用必須在同一個 Lock 區塊內完成
                with title_lock:
                    if normalized_title not in used_titles:
                        used_titles.add(normalized_title)
                        title_is_unique = True
                    else:
                        title_is_unique = False

                # 3. 如果唯一，成功跳出迴圈
                if title_is_unique:
                    break

                # 4. 如果重複，執行重試
                retry_count += 1
                print(
                    f"   🔄 [Duplicate] Retrying title ({retry_count}/{max_retries})..."
                )

                regen_prompt = (
                    f"The title '{raw_title}' is already taken. "
                    f"Generate a strictly DIFFERENT, catchy Pinterest title for this product.\n"
                    f"Format: [Title]: New Title Here"
                )

                try:
                    time.sleep(1.5)  # 稍微避讓 Rate Limit
                    resp_retry = call_api_with_retry(
                        local_client.models.generate_content,
                        model=selected_model,
                        contents=[ref_image, regen_prompt],
                    )
                    new_data = parse_text_output(extract_clean_text(resp_retry))

                    if "ERROR" not in new_data.get("Pin_Title", ""):
                        raw_title = new_data[
                            "Pin_Title"
                        ]  # 更新標題，準備進入下一次迴圈檢查
                    else:
                        # 如果生成失敗，加個隨機後綴避免死循環
                        raw_title = f"{raw_title} {random.randint(100, 999)}"
                except Exception as e:
                    # 如果 API 報錯，手動修改標題以確保唯一性
                    raw_title = f"{raw_title} {datetime.now().strftime('%S%f')[:4]}"

            # 如果重試多次還是失敗，強制加上隨機碼保底，防止重複
            if not title_is_unique:
                raw_title = f"{raw_title} {random.randint(1000, 9999)}"
                # 雖然醜一點，但至少保證上傳時不重複

            parsed_output["Pin_Title"] = raw_title
            # =================================================

        except Exception as e:
            error_context["Error_Message"] = f"API Error: {str(e)}"
            return {"error": True, "details": error_context}

    raw_hashtags = parsed_output.get("Pin_Hashtags", "")
    keywords_list = re.findall(r"#(\w+)", raw_hashtags)
    pin_keywords = ", ".join(keywords_list)

    return {
        "Pin_Name_For_Upload": f"{product_id}_{style_name}".replace(" ", "_"),
        "Affiliate_Link": product_row.get("Affiliate_Link", ""),
        "Image_name": image_name,
        "Image_Prompt_For_AI": final_img_prompt,
        "Pin_Title": parsed_output.get("Pin_Title", ""),
        "Pin_Description": parsed_output.get("Pin_Description", ""),
        "Pin_Keywords": pin_keywords,
        "Generated_Date": current_datetime,
        "Source_Product_Sheet": sheet_name,
        "Product_ID": product_id,
        "Applied_Style_ID": style_row.name,
        "Style_Name": style_name,
    }


# =======================================================
# 🔥 Main Execution
# =======================================================
if __name__ == "__main__":
    multiprocessing.freeze_support()

    log(f"\n⚙ Starting execution with Workers: {config_max_workers}")
    if config_max_workers == 1:
        log("🐢 Safe Batch Mode: Single request per product.")
    else:
        log(f"🐇 Multi-Thread Mode: {config_max_workers} workers.")

    try:
        for sheet_config_val in process_sheets:
            # 1. 智慧比對 Sheet
            target_sheet = None
            config_norm = str(sheet_config_val).strip().lower()
            for actual_s in actual_product_sheets:
                actual_norm = str(actual_s).strip().lower()
                if config_norm == actual_norm:
                    target_sheet = actual_s
                    if sheet_config_val != actual_s:
                        log(
                            f"✨ Smart Match: Config '{sheet_config_val}' mapped to Sheet '{target_sheet}'"
                        )
                    break

            if not target_sheet:
                log(f"\n⚠️  Warning: Sheet '{sheet_config_val}' not found.")
                continue

            # 🔥 [防護] Sheet 去重 (確保同一個實體 Sheet 只跑一次)
            if target_sheet in processed_real_sheets:
                log(f"🔄 Skipping duplicate sheet: {target_sheet} (Already processed)")
                continue
            processed_real_sheets.add(target_sheet)

            log(f"\n--- Processing: {target_sheet} ---")

            df_products = pd.read_excel(
                PRODUCT_FILE, sheet_name=target_sheet, engine="openpyxl"
            ).fillna("")
            df_products.columns = df_products.columns.str.strip()
            if "Pinterest_Angle" in df_products.columns:
                df_products.rename(
                    columns={"Pinterest_Angle": "Product_desc"}, inplace=True
                )

            # ======================================================
            # 🔥 [NEW] 建立圖片檔名對照表 (Case-Insensitive Map)
            # ======================================================
            # 讀取 ref_image 資料夾內所有檔案
            try:
                all_files_on_disk = os.listdir(REF_IMAGE_FOLDER)
            except Exception:
                all_files_on_disk = []

            # 建立字典: { '小寫檔名': '真實檔名' }
            # 例如: { 'bag.jpg': 'Bag.JPG', 'shoe.png': 'shoe.png' }
            image_map = {
                f.lower(): f
                for f in all_files_on_disk
                if os.path.isfile(os.path.join(REF_IMAGE_FOLDER, f))
            }

            job_list = []

            # 🔥 [防護] 本次 Sheet 的 Product ID 去重 (防止 Excel 裡有重複的 ID)
            processed_product_ids_in_sheet = set()

            for idx, product_row in df_products.iterrows():
                excel_row_num = idx + 2
                product_id = str(product_row.get("Product_ID", "N/A")).strip()

                # Check 0: Product ID 去重 (如果 ID 重複，直接跳過，不報錯)
                if product_id in processed_product_ids_in_sheet:
                    continue
                processed_product_ids_in_sheet.add(product_id)

                # Check 1: 必填欄位
                empty_cols = [
                    col
                    for col in REQUIRED_PRODUCT_COLS
                    if col not in df_products.columns
                    or pd.isna(product_row.get(col))
                    or str(product_row.get(col)).strip() == ""
                ]
                if empty_cols:
                    input_error_list.append(
                        {
                            "Source_Product_Sheet": target_sheet,
                            "Product_ID": product_id,
                            "Excel_Row_Index": excel_row_num,
                            "Error_Message": f"Skipped: Value missing in columns: {empty_cols}",
                        }
                    )
                    continue  # 💥 發現錯誤 -> 跳過該產品所有 Style -> 確保只報錯一次

                # Check 2: 圖片檔案
                raw_img_name = str(product_row.get("Image_name", "")).strip()

                # 1. 轉成小寫去查表
                actual_filename = image_map.get(raw_img_name.lower())

                if actual_filename:
                    # ✅ 找到了！使用硬碟上的真實檔名 (修正 Excel 大小寫誤差)
                    img_path = os.path.join(REF_IMAGE_FOLDER, actual_filename)

                    # 🔥 [重要] 把修正後的檔名寫回 row，讓後續 API 呼叫不出錯
                    product_row["Image_name"] = actual_filename
                else:
                    # ❌ 真的找不到
                    input_error_list.append(
                        {
                            "Source_Product_Sheet": target_sheet,
                            "Product_ID": product_id,
                            "Excel_Row_Index": excel_row_num,
                            "Error_Message": f"Missing Image File. Excel value: '{raw_img_name}' (Checked case-insensitive) vs Disk: Not Found.",
                        }
                    )
                    continue  # 💥 發現錯誤 -> 跳過

                # ✅ Product 驗證通過，才開始生成任務
                for style_id, style_row in df_style.iterrows():
                    job_list.append((product_row, style_row, target_sheet))
                    if test_single:
                        break

                if test_single and job_list:
                    break

            if not job_list:
                log(
                    f"   (No valid jobs found in sheet '{target_sheet}'. Check Input Errors.)"
                )
                continue

            results = []

            if config_max_workers == 1:
                total_jobs = len(job_list)
                for i, (row, style, sheet) in enumerate(job_list):
                    try:
                        s_name = style.get("style_name", "Default")
                        print(
                            f"\r   [BatchMode] Processing {i+1}/{total_jobs} ({row.get('Product_ID')} - {s_name})",
                            end="",
                            flush=True,
                        )
                        res = process_single_product(row, style, sheet)
                        results.append(res)

                        if res.get("error"):
                            print(" -> ❌ Failed")
                        else:
                            print(" -> ✅ Done")
                            if i < total_jobs - 1:
                                sleep_time = random.uniform(1, 3)
                                time.sleep(sleep_time)
                    except Exception as e:
                        print(f"\n❌ Error: {e}")
            else:
                with ThreadPoolExecutor(max_workers=config_max_workers) as executor:
                    futures = {
                        executor.submit(process_single_product, row, style, sheet): (
                            row,
                            style,
                        )
                        for row, style, sheet in job_list
                    }
                    completed_count = 0
                    total_count = len(futures)
                    for future in as_completed(futures):
                        try:
                            results.append(future.result())
                            completed_count += 1
                            print(
                                f"\r   [ThreadMode] Progress {completed_count}/{total_count}...",
                                end="",
                                flush=True,
                            )
                        except Exception:
                            pass
                print("")

            success_data = [
                r for r in results if isinstance(r, dict) and not r.get("error")
            ]
            error_data = [
                r["details"] for r in results if isinstance(r, dict) and r.get("error")
            ]

            if success_data:
                df = pd.DataFrame(success_data)
                cols = [
                    "Pin_Name_For_Upload",
                    "Affiliate_Link",
                    "Image_name",
                    "Image_Prompt_For_AI",
                    "Pin_Title",
                    "Pin_Description",
                    "Pin_Keywords",
                    "Generated_Date",
                    "Source_Product_Sheet",
                    "Product_ID",
                    "Applied_Style_ID",
                    "Style_Name",
                ]
                all_sheet_results[target_sheet] = df[
                    [c for c in cols if c in df.columns]
                ]

            if error_data:
                generation_error_list.extend(error_data)

    except KeyboardInterrupt:
        log("\n🛑 Interrupted! Saving data...")
    except Exception as e:
        log(f"\n❌ Error: {e}")
    finally:
        log("\n--- Saving Results ---")
        if all_sheet_results:
            with pd.ExcelWriter(output_path_generated, engine="openpyxl") as writer:
                for sheet, df in all_sheet_results.items():
                    df.to_excel(writer, sheet_name=sheet, index=False)
            log(f"✓ Results: {output_path_generated}")

        all_errors = input_error_list + generation_error_list
        if all_errors:
            error_df = pd.DataFrame(all_errors)
            if "Excel_Row_Index" in error_df.columns:
                cols = [
                    "Source_Product_Sheet",
                    "Product_ID",
                    "Excel_Row_Index",
                    "Error_Message",
                ]
                error_df = error_df[
                    cols + [c for c in error_df.columns if c not in cols]
                ]
            error_df.to_excel(output_path_input_errors, index=False)
            log(f"⚠ Errors: {output_path_input_errors}")

        log(f"📝 Log: {LOG_FILE_PATH}")
        input("Press Enter to exit...")
