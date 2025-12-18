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
from PIL import Image, UnidentifiedImageError  # 🔥 確保引入這個錯誤類型

# 忽略 pandas 的 FutureWarning
warnings.filterwarnings("ignore")


# =======================================================
# 📂 核心路徑與 Log 設定
# =======================================================
def get_base_path():
    """判斷 EXE 或 Python 環境，回傳根目錄"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = get_base_path()


# =======================================================
# 🛠️ [NEW] 自動釋放資源函式 (Self-Extracting Logic)
# =======================================================
def release_initial_files():
    """
    EXE 啟動時檢查：
    如果外部沒有設定檔，就從 EXE 內部 (sys._MEIPASS) 複製出來。
    """

    def get_internal_path(filename):
        if hasattr(sys, "_MEIPASS"):
            return os.path.join(sys._MEIPASS, filename)
        else:
            return os.path.join(BASE_DIR, filename)

    # 🔥 更新：加入 image_generation_instruction.txt
    assets_to_release = ["Config_Data.xlsx", ".env", "image_generation_instruction.txt"]

    print("\n🔍 Checking for essential files...")

    # 取得目前目錄檔案列表 (用於 Config 判斷)
    try:
        current_files_in_dir = os.listdir(BASE_DIR)
    except Exception:
        current_files_in_dir = []

    for filename in assets_to_release:
        target_path = os.path.join(BASE_DIR, filename)
        need_to_copy = True

        # 1. Config 檔特殊檢查：如果有任何 Config_Data*.xlsx 就不生成，避免覆蓋使用者的設定
        if filename == "Config_Data.xlsx":
            existing_configs = [
                f
                for f in current_files_in_dir
                if f.lower().startswith("config_data") and f.lower().endswith(".xlsx")
            ]
            if existing_configs:
                print(
                    f"   ✅ Found existing config(s): {existing_configs}. Skipping default generation."
                )
                need_to_copy = False

        # 2. 其他檔案 (如 .env, txt)：只要存在就跳過，不覆蓋
        if os.path.exists(target_path):
            need_to_copy = False

        # 3. 執行釋放
        if need_to_copy:
            internal_source = get_internal_path(filename)
            if os.path.exists(internal_source):
                try:
                    shutil.copy2(internal_source, target_path)
                    print(f"   📦 Auto-generated missing file: {filename}")
                except Exception as e:
                    print(f"   ⚠️ Failed to release {filename}: {e}")
            else:
                pass  # 開發模式下可能無此內部資源


# =======================================================
# 🛠️ 2. Demo 檔案生成 (安全檢查，絕不覆蓋)
# =======================================================
def ensure_demo_file_exists():
    """
    檢查 Generated_Content 資料夾內是否有 Demo 檔案。
    若無 -> 生成。
    若有 -> 跳過 (保護使用者檔案)。
    """
    # 預設 Demo 資料夾與檔名
    default_folder = os.path.join(BASE_DIR, "Generated_Content")
    demo_filename = "Demo_Input_For_Image_Gen.xlsx"
    target_path = os.path.join(default_folder, demo_filename)

    # 1. 確保資料夾存在
    if not os.path.exists(default_folder):
        try:
            os.makedirs(default_folder, exist_ok=True)
            print(f"   📁 Created folder: Generated_Content")
        except Exception as e:
            print(f"   ❌ Error creating folder: {e}")
            return

        print(f"   🎁 Extracting Demo Input File: {demo_filename}")

        # 4. 尋找來源檔案 (支援 EXE 內部路徑 與 開發環境路徑)
        source_path = None

        if hasattr(sys, "_MEIPASS"):
            # [打包後] 位於 EXE 內部的暫存資料夾
            source_path = os.path.join(sys._MEIPASS, demo_filename)
        else:
            # [開發模式] 位於專案的 sample_files 資料夾
            # 假設您的結構是 sample_files/Demo_Input_For_Image_Gen.xlsx
            source_path = os.path.join(BASE_DIR, "sample_files", demo_filename)

        # 5. 執行複製
        if source_path and os.path.exists(source_path):
            try:
                shutil.copy2(source_path, target_path)
                print(f"      ✅ Demo file extracted successfully.")
            except Exception as e:
                print(f"      ❌ Failed to extract demo file: {e}")
        else:
            # 萬一連來源都找不到 (例如開發環境路徑指錯)
            print(f"      ⚠️ Warning: Source demo file not found at {source_path}")
            # 這裡可以保留舊的 pd.DataFrame 邏輯當作最後備案，或直接報錯

    # 2. 🔥 關鍵檢查：如果檔案已存在，絕對不覆蓋，直接結束函式
    if os.path.exists(target_path):
        # 這裡不特別 print，以免干擾 Log，保持安靜
        return


# 🔥 程式啟動時，依序執行檢查
release_initial_files()
ensure_demo_file_exists()  # <--- 這裡加入 Demo 檢查

# 設定 Log 資料夾與檔案
LOG_FOLDER = os.path.join(BASE_DIR, "Logs")
os.makedirs(LOG_FOLDER, exist_ok=True)
current_time_str = datetime.now().strftime("%Y%m%d-%H%M%S")
LOG_FILE_PATH = os.path.join(LOG_FOLDER, f"log_image_gen-{current_time_str}.txt")

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
log(f"🚀 Generic Batch Image Generator")
log(f"📂 Working Directory: {BASE_DIR}")
log(f"📝 Log file: {LOG_FILE_PATH}")
print("-" * 50)

# 設定其他檔案路徑
ENV_FILE_PATH = os.path.join(BASE_DIR, ".env")
OUTPUT_FOLDER = os.path.join(BASE_DIR, "Generated_Images")
INSTRUCTION_FILE = os.path.join(BASE_DIR, "image_generation_instruction.txt")
REF_IMAGE_FOLDER = os.path.join(BASE_DIR, "ref_image")  # 定義全域變數

os.makedirs(OUTPUT_FOLDER, exist_ok=True)
if not os.path.exists(REF_IMAGE_FOLDER):
    os.makedirs(REF_IMAGE_FOLDER)
    print(f"🆕 Auto-created default image folder: {REF_IMAGE_FOLDER}")

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
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
    return df


# Self-Healing: Check for required files
def initialize_image_system():
    required_files = ["Config_Data.xlsx", "image_generation_instruction.txt", ".env"]
    base_path = sys._MEIPASS if getattr(sys, "frozen", False) else ""
    if not base_path:
        return

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
    "ID": ["id", "product_id"],
    "Prompt": ["prompt", "image_prompt_for_ai"],
    "Image_name": ["image_name", "image_reference"],
    "Pin_Name": ["pin_name_for_upload"],
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
        max_retries = retry_settings.get("max_retries", 3)
        initial_backoff = retry_settings.get("retry_backoff", 5)

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
                    raise e  # 超過次數，拋出錯誤

                wait_time = initial_backoff * attempt  # 線性或指數退避
                log(
                    f"⚠️ API Busy (429), retrying ({attempt}/{max_retries}) in {wait_time}s..."
                )
                time.sleep(wait_time)
            else:
                raise e  # 其他錯誤直接拋出


def validate_aspect_ratio_support(model_name, current_ratio, ratios_df):
    """
    🔥 檢查當前模型是否支援選定的長寬比 (已優化顯示格式：去除秒數與開頭0)
    """

    # 內部小函式：用來清理格式 (例如 09:16:00 -> 9:16)
    def clean_ratio_fmt(val):
        s = str(val).strip()
        if s.count(":") >= 2:  # 去除秒數 (09:16:00 -> 09:16)
            s = s.rsplit(":", 1)[0]
        if s.startswith("0"):  # 去除開頭 0 (09:16 -> 9:16)
            s = s[1:]
        return s

    if ratios_df.empty:
        return "1:1"

    # 1. 清理傳入的當前比例
    clean_current = clean_ratio_fmt(current_ratio)

    # 2. 找出 Excel 中對應的那一行 (需比對清理後的數值)
    row = pd.DataFrame()
    for _, r in ratios_df.iterrows():
        if clean_ratio_fmt(r["aspect_ratio"]) == clean_current:
            row = r.to_frame().T
            break

    # 如果找不到對應設定，暫時回傳清理後的數值 (容錯)
    if row.empty:
        return clean_current

    supported_models_str = (
        str(row.iloc[0].get("supported_models", "All")).lower().strip()
    )

    # 3. 檢查相容性
    is_compatible = False
    model_lower = model_name.lower()

    if "all" in supported_models_str:
        is_compatible = True
    elif "gemini" in supported_models_str and "gemini" in model_lower:
        is_compatible = True
    elif "imagen" in supported_models_str and "imagen" in model_lower:
        is_compatible = True
    # 排除例外
    if "gemini only" in supported_models_str and "imagen" in model_lower:
        is_compatible = False

    if is_compatible:
        return clean_current

    # 4. 衝突時顯示選單 (這裡套用清理邏輯)
    print(
        f"\n⚠️  CONFLICT: Ratio '{clean_current}' is marked as '{row.iloc[0]['supported_models']}',"
    )
    print(f"    but you selected model: '{model_name}'.")
    print("\n👉  Please select a compatible Aspect Ratio:")

    valid_options = []
    seen = set()  # 用來過濾重複 (例如 9:16 和 09:16:00 清理後是一樣的)

    for _, r_row in ratios_df.iterrows():
        s_str = str(r_row.get("supported_models", "All")).lower()
        opt_compatible = False
        if "all" in s_str:
            opt_compatible = True
        elif "gemini" in s_str and "gemini" in model_lower:
            opt_compatible = True
        elif "imagen" in s_str and "imagen" in model_lower:
            opt_compatible = True

        if opt_compatible:
            fmt_opt = clean_ratio_fmt(r_row["aspect_ratio"])
            if fmt_opt not in seen:
                valid_options.append(fmt_opt)
                seen.add(fmt_opt)

    for i, opt in enumerate(valid_options):
        print(f"   [{i+1}] {opt}")
    print("   [Q] Quit")

    while True:
        choice = input("👉 Select Option (Number): ").strip().lower()
        if choice == "q":
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
def process_single_item(
    row,
    target_ratio,
    sheet_name,
    model_name,
    use_ref,
    instruction,
    col_map,
    retry_settings,
    excel_filename,
    custom_img_folder=None,
):
    """
    雙引擎處理邏輯 (含：自動建立資料夾 + 優化錯誤訊息提示)
    """
    item_id = "Unknown"
    try:
        item_id = str(row[col_map["ID"]] if col_map["ID"] in row else "Unknown").strip()
        prompt_text = str(
            row[col_map["Prompt"]] if col_map["Prompt"] in row else ""
        ).strip()

        if not prompt_text:
            return {
                "status": "Error",
                "error": "Skipped: 'Prompt' column is empty.",
                "id": item_id,
                "sheet": sheet_name,
            }

    except Exception as e:
        return {
            "status": "Error",
            "error": f"Column read error: {e}",
            "id": item_id,
            "sheet": sheet_name,
        }

    ar_val = str(target_ratio if target_ratio else "1:1").strip()
    if ar_val.count(":") == 2:
        ar_val = ar_val.rsplit(":", 1)[0]
    if ar_val.startswith("0"):
        ar_val = ar_val[1:]
    ratio_name = ar_val.replace(":", "x")

    final_prompt_text = (
        f"{instruction}\n\nAspect Ratio: {ar_val}\nPrompt: {prompt_text}"
    )

    image_bytes = None
    input_mime_type = "image/jpeg"

    # ============================================
    # 🔍 圖片檢驗邏輯 (優化錯誤訊息版)
    # ============================================
    if use_ref:
        img_col = col_map.get("Image_name")
        img_name = str(row[img_col] if img_col and img_col in row else "").strip()

        # 🔥 優化訊息 1: 欄位空白
        if not img_name:
            return {
                "status": "Error",
                "error": "Missing Filename: 'Image_name' column is empty in Excel.",
                "id": item_id,
                "sheet": sheet_name,
            }

        # 建立多重搜尋路徑
        possible_paths = []
        # 1. 自訂路徑
        if custom_img_folder and os.path.isdir(custom_img_folder):
            possible_paths.append(os.path.join(custom_img_folder, img_name))

        # 2. 預設 ref_image 資料夾 (現在程式會自動建立了)
        possible_paths.append(os.path.join(REF_IMAGE_FOLDER, img_name))

        # 3. 根目錄
        possible_paths.append(os.path.join(BASE_DIR, img_name))

        found_img_path = next((p for p in possible_paths if os.path.exists(p)), None)

        # 🔥 優化訊息 2: 找不到圖片時，列出搜尋過的路徑
        if not found_img_path:
            scanned_locs = "\n       ".join(possible_paths)
            err_msg = f"Image Not Found: '{img_name}'\n     ℹ️ Scanned locations:\n       {scanned_locs}"
            return {
                "status": "Error",
                "error": err_msg,
                "id": item_id,
                "sheet": sheet_name,
            }

        try:
            with Image.open(found_img_path) as img:
                img.verify()

            if found_img_path.lower().endswith(".png"):
                input_mime_type = "image/png"
            elif found_img_path.lower().endswith(".webp"):
                input_mime_type = "image/webp"

            with open(found_img_path, "rb") as image_file:
                image_bytes = image_file.read()

        except UnidentifiedImageError:
            return {
                "status": "Error",
                "error": f"Corrupt/Invalid Image File: {img_name}",
                "id": item_id,
                "sheet": sheet_name,
            }
        except Exception as e:
            return {
                "status": "Error",
                "error": f"Image Read Error: {e}",
                "id": item_id,
                "sheet": sheet_name,
            }

    # ============================================
    # 🚀 API 呼叫區塊
    # ============================================
    try:
        if "use_mock" in globals() and use_mock:
            time.sleep(0.1)
            return {
                "status": "Mock Success",
                "path": f"mock/{excel_filename}/{item_id}.png",
            }

        img_result_data = None
        output_ext = ".png"

        is_imagen = "imagen" in model_name.lower()

        if is_imagen:
            if image_bytes:
                return {
                    "status": "Error",
                    "error": "Imagen does not support Ref Image",
                    "id": item_id,
                    "sheet": sheet_name,
                }

            config_params = {
                "number_of_images": 1,
                "aspect_ratio": ar_val,
                "output_mime_type": "image/jpeg",
            }
            response = call_api_with_retry(
                global_client.models.generate_images,
                model=model_name,
                prompt=final_prompt_text,
                config=config_params,
                retry_settings=retry_settings,
            )
            if response.generated_images:
                img_result_data = response.generated_images[0].image.image_bytes
                output_ext = ".jpg"
            else:
                return {
                    "status": "Error",
                    "error": "Imagen returned no images",
                    "id": item_id,
                    "sheet": sheet_name,
                }
        else:
            parts = [types.Part.from_text(text=final_prompt_text)]
            if image_bytes:
                parts.append(
                    types.Part.from_bytes(data=image_bytes, mime_type=input_mime_type)
                )

            gen_config = types.GenerateContentConfig(response_modalities=["IMAGE"])
            response = call_api_with_retry(
                global_client.models.generate_content,
                model=model_name,
                contents=[types.Content(role="user", parts=parts)],
                config=gen_config,
                retry_settings=retry_settings,
            )

            if response.candidates:
                for candidate in response.candidates:
                    if candidate.content and candidate.content.parts:
                        for part in candidate.content.parts:
                            if part.inline_data and part.inline_data.data:
                                img_result_data = part.inline_data.data
                                if part.inline_data.mime_type:
                                    guessed = mimetypes.guess_extension(
                                        part.inline_data.mime_type
                                    )
                                    if guessed:
                                        output_ext = guessed
                                        if output_ext == ".jpe":
                                            output_ext = ".jpg"
                                break
                    if img_result_data:
                        break

            if not img_result_data:
                err_text = (
                    response.text[:100]
                    if response and response.text
                    else "No content returned"
                )
                return {
                    "status": "Error",
                    "error": f"Gemini Refused: {err_text}",
                    "id": item_id,
                    "sheet": sheet_name,
                }

        if img_result_data:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            clean_sheet = re.sub(r'[\\/*?:"<>|]', "", str(sheet_name))
            clean_id = re.sub(r'[\\/*?:"<>|]', "", str(item_id))
            excel_subfolder = os.path.join(OUTPUT_FOLDER, excel_filename)
            os.makedirs(excel_subfolder, exist_ok=True)
            filename = f"{clean_sheet}_{clean_id}_{ratio_name}_{timestamp}{output_ext}"
            save_path = os.path.join(excel_subfolder, filename)

            with open(save_path, "wb") as f:
                f.write(img_result_data)
            return {
                "status": "Success",
                "path": save_path,
                "id": item_id,
                "sheet": sheet_name,
            }
        else:
            return {
                "status": "Error",
                "error": "Unknown: Data extraction failed",
                "id": item_id,
                "sheet": sheet_name,
            }

    except Exception as e:
        return {"status": "Error", "error": str(e), "id": item_id, "sheet": sheet_name}


def select_config_file():
    """
    掃描當前目錄下所有以 'Config_Data' 開頭的 Excel 檔案。
    """
    try:
        current_dir = BASE_DIR
        # 搜尋 Config_Data 開頭且是 Excel 的檔案，排除暫存檔(~$開頭)
        config_files = [
            f
            for f in os.listdir(current_dir)
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
        print("\n" + "=" * 50)
        print(f" 📂 [Select Configuration] Found {len(config_files)} files:")
        print("=" * 50)

        for idx, file_name in enumerate(config_files):
            # 如果是標準名稱，標記為 Default (選擇性顯示)
            mark = " (Standard)" if file_name == "Config_Data.xlsx" else ""
            print(f"  [{idx + 1}] {file_name}{mark}")

        print("=" * 50)

        while True:
            selection = input(
                f"👉 Enter number (1-{len(config_files)}) to select: "
            ).strip()

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
    """
    settings = {
        "model_name": "gemini-2.5-flash-image",
        "aspect_ratio": "1:1",
        "max_workers": 1,
        "retry_settings": {"max_retries": 3, "retry_backoff": 5},  # 預設值
        "ratios_df": pd.DataFrame(),
        "models_df": pd.DataFrame(),  # 🔥 新增：用來存放完整的模型設定表
    }

    if not os.path.exists(config_path):
        log(f"⚠️ Config file not found at {config_path}. Using defaults.")
        return settings

    try:
        # 1. Model Config
        try:
            df = pd.read_excel(config_path, sheet_name="Model_Config")
            df = normalize_cols(df)
            settings["models_df"] = df  # 🔥 保存完整 DataFrame

            is_selected = (
                df["selection"]
                .astype(str)
                .str.lower()
                .isin(["true", "1", "yes", "y", "on"])
            )
            is_image_type = (
                df["model_type"].astype(str).str.strip().str.lower() == "image"
            )

            sel = df[is_selected & is_image_type]

            if not sel.empty:
                settings["model_name"] = str(
                    sel.iloc[0].get("model_name", settings["model_name"])
                ).strip()
                log(f"✅ Loaded Image Model from Config: {settings['model_name']}")
            else:
                log(
                    "⚠️ No valid 'Image' model selected in Config. Using default model: Gemini 2.5 Flash Image."
                )
        except Exception as e:
            log(f"⚠️ Error reading Model_Config: {e}")

        # 2. Concurrency Config (🔥 完整讀取)
        try:
            df = pd.read_excel(config_path, sheet_name="Concurrency_Config")
            df = normalize_cols(df)
            d = dict(zip(df["parameter"].astype(str).str.upper(), df["value"]))

            # 讀取 Max Workers
            if "MAX_WORKERS" in d:
                settings["max_workers"] = int(float(d["MAX_WORKERS"]))

            # 讀取 Retry 相關設定
            retry_config = {}
            if "API_RETRY_ATTEMPTS" in d:
                retry_config["max_retries"] = int(float(d["API_RETRY_ATTEMPTS"]))
            if "RETRY_INITIAL_BACKOFF" in d:
                retry_config["retry_backoff"] = int(float(d["RETRY_INITIAL_BACKOFF"]))

            # 更新 settings
            settings["retry_settings"].update(retry_config)

            log(
                f"✅ Loaded Concurrency: Workers={settings['max_workers']}, Retries={settings['retry_settings']['max_retries']}"
            )

        except Exception as e:
            log(f"⚠️ Error reading Concurrency_Config: {e}")

        # 3. Aspect Ratio
        try:
            df = pd.read_excel(config_path, sheet_name="Aspect_Ratio")
            df = normalize_cols(df)
            settings["ratios_df"] = df

            is_selected = (
                df["selection"]
                .astype(str)
                .str.lower()
                .isin(["true", "1", "yes", "y", "on"])
            )
            sel_ar = df[is_selected]

            if not sel_ar.empty:
                raw_ar = str(sel_ar.iloc[0].get("aspect_ratio", "1:1")).strip()
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
    print("\n" + "=" * 30 + "\n   🛠️  RUNTIME SETTINGS\n" + "=" * 30)

    t_in = input("👉 Run single test mode? (Y/N) [default: Y]: ").strip().upper()
    test_single = False if t_in == "N" else True

    r_in = (
        input("👉 Do you want to upload a reference image? (Y/N) [default: N]: ")
        .strip()
        .upper()
    )
    use_ref = True if r_in == "Y" else False

    custom_img_folder = None

    # 🔥 優化互動邏輯：告知 -> 詢問 (Y/N) -> 動作
    if use_ref:
        print("-" * 30)
        print("📁 REFERENCE IMAGE SETUP")
        print(f"   ℹ️  Default Folder: {REF_IMAGE_FOLDER}")
        print("       (Please place your images here)")

        # 詢問：圖片是否在預設資料夾？
        use_default = (
            input("👉 Are your images in this default folder? (Y/N) [default: Y]: ")
            .strip()
            .upper()
        )

        if use_default == "N":
            # 選 N -> 輸入自訂路徑
            custom_input = input("👉 Enter your CUSTOM folder path: ").strip()

            if custom_input and os.path.isdir(custom_input):
                custom_img_folder = custom_input
                print(f"✅ Image Source Set to: {custom_img_folder}")
            else:
                # 防呆
                print(f"❌ Invalid folder: '{custom_input}'")
                print(f"🔄 Reverting to Default: {REF_IMAGE_FOLDER}")
                custom_img_folder = None
        else:
            # 選 Y 或直接 Enter -> 使用預設
            print(f"✅ Using Default Folder: {REF_IMAGE_FOLDER}")
            custom_img_folder = None

    # --- 模型篩選邏輯 (保持不變) ---
    valid_models = []
    default_img2img_models = [
        "gemini-3-pro-image-preview",
        "gemini-2.5-flash-image",
        "gemini-2.5-flash-image-preview",
    ]

    if not models_df.empty:
        try:
            if use_ref:
                mask = (
                    models_df["image_to_image"]
                    .astype(str)
                    .str.lower()
                    .isin(["true", "1", "yes", "y", "on"])
                )
                valid_models = models_df[mask]["model_name"].tolist()
            else:
                mask = models_df["model_type"].astype(str).str.lower() == "image"
                valid_models = models_df[mask]["model_name"].tolist()
        except Exception:
            pass

    if not valid_models:
        valid_models = (
            default_img2img_models
            if use_ref
            else (default_img2img_models + ["imagen-4.0-generate-001"])
        )

    final_model = initial_model_name.strip()
    if final_model not in valid_models:
        print("-" * 30)
        if final_model:
            print(f"⚠️  Configured model '{final_model}' is NOT compatible.")
        final_model = valid_models[0]
        print(f"🔄  Recommended: {final_model}")
        print("👉  Please select a valid model:")
        for idx, m in enumerate(valid_models):
            print(f"   [{idx+1}] {m}")

        while True:
            sel = input("👉 Enter number: ").strip()
            if sel == "":
                break
            if sel.isdigit() and 0 <= int(sel) - 1 < len(valid_models):
                final_model = valid_models[int(sel) - 1]
                break
            print("⚠️ Invalid selection.")
    else:
        print("-" * 30)
        print(f"✅ Using Configured Model: [{final_model}]")

    print("-" * 30)
    print(f"🤖 Final Model : {final_model}")
    print(f"🧪 Test Mode   : {'ON' if test_single else 'OFF'}")
    print(f"🖼️  Ref Image   : {'ON' if use_ref else 'OFF'}")

    if use_ref:
        active_src = custom_img_folder if custom_img_folder else "Default (ref_image)"
        print(f"📂 Image Source: {active_src}")

    print("-" * 30 + "\n")

    return test_single, use_ref, final_model, custom_img_folder


def find_actual_col_name(df_cols, key_alias):
    aliases = COL_ALIASES.get(key_alias, [key_alias.lower()])
    for alias in aliases:
        if alias in df_cols:
            return alias
    return None


# =======================================================
# 🚀 主程式 (Main)
# =======================================================
if __name__ == "__main__":
    multiprocessing.freeze_support()
    ALL_ERROR_RECORDS = []
    try:
        initialize_image_system()
        default_instruction = "Generate a high-quality image based on the prompt."
        ensure_template_exists(INSTRUCTION_FILE, default_instruction)

        log("\n--- API Setup ---")
        env_config = dotenv_values(ENV_FILE_PATH)
        GEMINI_API_KEY = env_config.get("GEMINI_API_KEY")

        if not GEMINI_API_KEY:
            log(f"⚠️ GEMINI_API_KEY not detected in .env")
            use_mock = input("   ❌ Use simulation (Mock) mode? (Y/N): ").lower() == "y"
            if not use_mock:
                sys.exit()
        else:
            try:
                global_client = genai.Client(api_key=GEMINI_API_KEY)
                log("✓ Global Gemini Client initialized.")
            except Exception as e:
                log(f"❌ API Client Init Error: {e}")
                sys.exit(1)

        instruction_content = load_template(INSTRUCTION_FILE)

        target_config_path = select_config_file()

        if target_config_path:
            log(f"⏳ Loading settings from: {os.path.basename(target_config_path)}...")
            settings = load_settings(target_config_path)
        else:
            print("\n" + "!" * 60)
            log("⚠️  NO CONFIGURATION FILE FOUND (Config_Data*.xlsx)")
            log("👉  System will run with [DEFAULT SETTINGS] (Gemini, 1:1, etc.)")
            print("!" * 60 + "\n")
            settings = load_settings("DUMMY_PATH_FOR_DEFAULTS")

        test_single, use_ref_image, target_model, custom_img_folder = (
            configure_runtime_settings(settings["model_name"], settings["models_df"])
        )

        validated_ratio = validate_aspect_ratio_support(
            target_model, settings["aspect_ratio"], settings["ratios_df"]
        )

        default_folder = "Generated_Content"
        f_in = input(
            f"👉 Enter input folder name (default: '{default_folder}'): "
        ).strip()
        target_folder_name = f_in if f_in else default_folder
        target_folder_path = os.path.join(BASE_DIR, target_folder_name)

        if not os.path.exists(target_folder_path):
            print(
                f"❌ Folder '{target_folder_name}' not found. Scanning root directory instead..."
            )
            target_folder_path = BASE_DIR

        all_files = [
            f
            for f in os.listdir(target_folder_path)
            if f.lower().endswith((".xlsx", ".xls")) and not f.startswith("~$")
        ]
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

            # 🔥 [CRITICAL FIX] 初始化變數 (避免 NameError)
            executed_any_job_in_this_file = False

            excel_clean_name = os.path.splitext(file_name)[0]

            log(f"\n📦 Processing File: {file_name}")

            try:
                xls = pd.ExcelFile(file_path)
            except Exception as e:
                log(f"❌ Read Error: {e}")
                continue

            excluded_sheets = [
                "config",
                "ratios",
                "dropdowns",
                "lists",
                "data validation",
                "readme",
                "model_config",
            ]

            for sheet in xls.sheet_names:
                if sheet.lower() in excluded_sheets:
                    continue

                try:
                    df = pd.read_excel(file_path, sheet_name=sheet).fillna("")
                    df = normalize_cols(df)
                except:
                    continue

                id_col = find_actual_col_name(df.columns, "ID")
                prompt_col = find_actual_col_name(df.columns, "Prompt")
                if not id_col or not prompt_col:
                    continue

                pin_col = find_actual_col_name(df.columns, "Pin_Name")

                col_map = {"ID": id_col, "Prompt": prompt_col}

                if pin_col:
                    col_map["Pin_Name"] = pin_col

                if use_ref_image:
                    img_col = find_actual_col_name(df.columns, "Image_name")
                    if not img_col:
                        log(
                            f"  ⚠️  Sheet '{sheet}': Ref Image ON but 'Image_name' column missing. Skipping."
                        )
                        continue
                    col_map["Image_name"] = img_col

                log(f"  📂 Sheet: {sheet}")

                jobs = []
                for _, row in df.iterrows():
                    # 取出並清理 ID 與 Prompt
                    r_id = str(row[id_col]).strip()
                    r_prompt = str(row[prompt_col]).strip()

                    # 🔴 檢驗邏輯優化：如果缺少 ID 或 Prompt，直接記錄錯誤，不跳過
                    if not r_id or not r_prompt:
                        print(f"     ⚠️ Skipping Row: Missing ID or Prompt")
                        ALL_ERROR_RECORDS.append(
                            {
                                "File": file_name,
                                "Sheet": sheet,
                                "ID": r_id if r_id else "MISSING_ID",
                                "Error Message": "Skipped: Missing ID or Prompt",
                                "Timestamp": datetime.now().strftime(
                                    "%Y-%m-%d %H:%M:%S"
                                ),
                            }
                        )
                        continue  # 記錄完錯誤後再跳過

                    # 通過檢查，加入工作排程
                    jobs.append(
                        (
                            row,
                            validated_ratio,
                            sheet,
                            target_model,
                            use_ref_image,
                            instruction_content,
                            col_map,
                            settings["retry_settings"],
                            excel_clean_name,
                            custom_img_folder,
                        )
                    )
                    if test_single:
                        break

                if not jobs:
                    log("     ℹ️  No valid jobs.")
                    continue

                # 🔥 [CRITICAL FIX] 標記：確認有任務要執行
                executed_any_job_in_this_file = True

                log(
                    f"     🔥 Starting {len(jobs)} tasks (Max Workers: {settings['max_workers']})..."
                )

                with ThreadPoolExecutor(
                    max_workers=settings["max_workers"]
                ) as executor:
                    futures = {
                        executor.submit(process_single_item, *j): j for j in jobs
                    }
                    for i, f in enumerate(as_completed(futures)):
                        res = f.result()

                        # 🔥 修改：檢查是否為 Error，如果是則記錄
                        if res.get("status") == "Error":
                            print(f"\n     ❌ Error: {res.get('error')}")
                            # 收集到全域列表
                            ALL_ERROR_RECORDS.append(
                                {
                                    "File": file_name,
                                    "Sheet": res.get("sheet", sheet),
                                    "ID": res.get("id", "Unknown"),
                                    "Error Message": res.get("error"),
                                    "Timestamp": datetime.now().strftime(
                                        "%Y-%m-%d %H:%M:%S"
                                    ),
                                }
                            )
                        else:
                            print(f"\n     ✅ Saved: {res.get('path')}")

                if test_single:
                    print("  🛑 Test mode: Stopping after first active sheet.")
                    break  # 跳出 Sheet 迴圈

            # =======================================================
            # 🔥 [CRITICAL FIX] 檢查變數狀態，跳出最外層 File 迴圈
            # =======================================================
            if test_single and executed_any_job_in_this_file:
                print("🛑 Test mode: Job done. Exiting file loop.")
                break

    except Exception as e:
        log(f"\n❌ Fatal Error: {e}")
        import traceback

        traceback.print_exc()

    input("\n✅ Execution finished. Press Enter to exit...")
