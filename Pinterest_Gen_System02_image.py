print("🚀 System initializing... Please wait while libraries are loading.")

import sys
import os
import time
import base64
import random
import logging
import shutil  # ✅ 用於複製檔案
from io import BytesIO
from PIL import Image
import pandas as pd
from google import genai
from google.genai import types
from dotenv import dotenv_values
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, total=None, desc="", unit="", ncols=0):
        return iterable

MAX_WORKERS = 5

# ------------------- Path setup -------------------
if getattr(sys, 'frozen', False):
    # EXE 模式：
    # script_dir = EXE 所在的外部資料夾 (我們要把檔案釋放到這裡)
    script_dir = os.path.dirname(sys.executable)
    # internal_resource_dir = EXE 內部的暫存資料夾 (預設檔案藏在這裡)
    internal_resource_dir = sys._MEIPASS 
else:
    # 開發模式：
    script_dir = os.path.dirname(os.path.abspath(__file__))
    internal_resource_dir = script_dir

ENV_FILE_PATH = os.path.join(script_dir, ".env")
GENERATED_CONTENT_FOLDER = os.path.join(script_dir, "Generated_Content")
REF_IMAGE_FOLDER = os.path.join(script_dir, "ref_image")
INSTRUCTION_FILE = os.path.join(script_dir, "image_generation_instruction.txt")
LOG_DIR = os.path.join(script_dir, "Logs")

# ------------------- Self-Healing: Restore Missing Files -------------------
def restore_default_files():
    """
    從 EXE 內部釋放必要檔案到外部。
    關鍵邏輯：只在「外部檔案不存在」時才複製，確保不覆蓋舊資料。
    """
    required_files = [
        "Pinterest_Affiliate_Data.xlsx",
        "Pinterest_Affiliate_Product.xlsx",
        "image_generation_instruction.txt",
        ".env"
    ]

    print("\n🔍 Checking system integrity...")
    
    for filename in required_files:
        target_path = os.path.join(script_dir, filename)
        
        # ⚠️ 這裡是最重要的保護機制：
        # 只有當檔案「不存在」時，才從內部複製出來。
        if not os.path.exists(target_path):
            source_path = os.path.join(internal_resource_dir, filename)
            
            if os.path.exists(source_path):
                try:
                    shutil.copy2(source_path, target_path)
                    print(f"   ✨ Initialized missing file: {filename}")
                except Exception as e:
                    print(f"   ⚠️ Failed to restore {filename}: {e}")
            else:
                # 這種情況通常不會發生，除非打包時漏了
                print(f"   ❌ Critical: Internal resource missing for {filename}")
        else:
            # 檔案已存在，表示可能是舊用戶的資料，直接跳過，不做任何動作
            # print(f"   ✓ Found existing: {filename} (Skipping overwrite)")
            pass

# ------------------- Logging Setup -------------------
def setup_logging():
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = f"Image_Gen_Log_{timestamp}.txt"
    log_filepath = os.path.join(LOG_DIR, log_filename)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filepath, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return log_filepath

# ------------------- Instruction Loader -------------------
default_instruction = """
Use the provided product image as the main object in the composition.
Ensure the final image is Pinterest-ready: visually appealing, clean, and photorealistic.
"""

def load_instruction_text():
    # 因為 restore_default_files 會確保檔案存在，所以這裡優先讀檔
    if os.path.isfile(INSTRUCTION_FILE):
        with open(INSTRUCTION_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return default_instruction

# ------------------- API Call Worker Function -------------------
def generate_and_save_image(client, row_data, instruction_text, ASPECT_RATIO, MODEL_NAME, output_dir):
    pin_name = str(row_data.get("Pin_Name_For_Upload", "")).strip()
    image_prompt = str(row_data.get("Image_Prompt_For_AI", "")).strip()
    image_name = str(row_data.get("Image_name", "")).strip()
    product_id = str(row_data.get("Product_ID", "")).strip()
    
    result = {"row_data": row_data.to_dict(), "Generation_Error": None, "Success": False}
    
    if not image_prompt or image_prompt.lower() == 'nan':
        result["Generation_Error"] = "❌ Missing Image Prompt."
        return result

    image_path = os.path.join(REF_IMAGE_FOLDER, image_name)
    if not os.path.isfile(image_path):
        result["Generation_Error"] = f"❌ Missing file: {image_name}"
        return result

    try:
        ref_image = Image.open(image_path)
    except Exception as e:
        result["Generation_Error"] = f"❌ Failed to open image: {e}"
        return result

    final_prompt = f"{image_prompt}\n\n{instruction_text}"
    contents = [final_prompt, ref_image]

    generate_config = types.GenerateContentConfig(
        response_modalities=["IMAGE", "TEXT"],
        image_config=types.ImageConfig(aspect_ratio=ASPECT_RATIO)
    )

    max_retries = 5
    retry_delay = 2
    generated_resp = None
    
    for attempt in range(max_retries):
        try:
            generated_resp = client.models.generate_content(
                model=MODEL_NAME,
                contents=contents,
                config=generate_config
            )
            break
        except Exception as e:
            error_str = str(e).lower()
            if "429" in error_str or "resource exhausted" in error_str or "503" in error_str:
                if attempt < max_retries - 1:
                    sleep_time = retry_delay + random.uniform(0, 1)
                    logging.debug(f"Rate limit hit for {product_id}, retrying in {sleep_time:.2f}s")
                    time.sleep(sleep_time)
                    retry_delay *= 2
                else:
                    result["Generation_Error"] = f"❌ Max retries reached: {e}"
                    return result
            else:
                result["Generation_Error"] = f"❌ API Error: {e}"
                return result

    if generated_resp and generated_resp.candidates and generated_resp.candidates[0].content.parts:
        for part in generated_resp.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                try:
                    img_bytes = part.inline_data.data
                    img = Image.open(BytesIO(img_bytes))
                    
                    safe_pin_name = "".join(c if c.isalnum() else "_" for c in pin_name)[:50]
                    timestamp = datetime.now().strftime("%m%d_%H%M%S")
                    filename = f"{safe_pin_name}_{timestamp}.png"
                    
                    save_path = os.path.join(output_dir, filename)
                    img.save(save_path)
                    
                    result["Success"] = True
                    return result
                except Exception as e:
                    result["Generation_Error"] = f"⚠️ Save failed: {e}"
                    return result
    
    if not result["Success"] and not result["Generation_Error"]:
        result["Generation_Error"] = "API returned no image data."

    return result

# ------------------- Main Execution -------------------

if __name__ == "__main__":
    # 1.【第一步】執行自我修復
    # 如果是新用戶，這一步會釋放出 .env 和 Excel
    # 如果是老用戶，這一步什麼都不會做，確保資料安全
    restore_default_files()

    # 2. 檢查工作目錄 (沒有才建立，避免 Crash)
    if not os.path.exists(GENERATED_CONTENT_FOLDER):
        os.makedirs(GENERATED_CONTENT_FOLDER, exist_ok=True)
        print(f"📁 Initialized folder: Generated_Content")

    if not os.path.exists(REF_IMAGE_FOLDER):
        os.makedirs(REF_IMAGE_FOLDER, exist_ok=True)
        print(f"📁 Initialized folder: ref_image")

    # 3. 初始化 Log
    log_file_path = setup_logging()
    
    print("\n=== Pinterest Image Generator ===")
    logging.info("=== Program Started ===")
    
    # 讀取 .env (restore_default_files 確保了它一定存在)
    env_config = dotenv_values(ENV_FILE_PATH)
    GEMINI_API_KEY = env_config.get("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        msg = "🛑 Missing GEMINI_API_KEY in .env file."
        print(msg)
        logging.error(msg)
        input("Press Enter to exit...")
        exit()
    
    client = genai.Client(api_key=GEMINI_API_KEY)

    # User Inputs
    TEST_SINGLE = input("Run single test? (Y/N): ").strip().lower() == 'y'
    ASPECT_RATIO = input("Aspect ratio (default 2:3): ").strip() or "2:3"
    MODEL_NAME = input("Model name (default gemini-2.5-flash-image): ").strip() or "gemini-2.5-flash-image"
    
    logging.info(f"Configuration: Single Test={TEST_SINGLE}, Ratio={ASPECT_RATIO}, Model={MODEL_NAME}")
    
    instruction_text = load_instruction_text()
    
    # 讀取 Excel
    excel_files = [f for f in os.listdir(GENERATED_CONTENT_FOLDER) if f.lower().endswith(".xlsx")]
    if not excel_files:
        msg = f"🛑 No Excel files found in '{GENERATED_CONTENT_FOLDER}' folder."
        print(msg)
        print("💡 Please make sure you have generated content using the Content Generator.")
        logging.warning(msg)
        input("\nPress Enter to exit...")
        exit()

    all_tasks = []
    
    print("\n--- Reading Excel files ---")
    for excel_file in excel_files:
        excel_path = os.path.join(GENERATED_CONTENT_FOLDER, excel_file)
        output_dir = os.path.join(GENERATED_CONTENT_FOLDER, os.path.splitext(excel_file)[0])
        os.makedirs(output_dir, exist_ok=True)

        try:
            xls = pd.ExcelFile(excel_path)
            for sheet_name in xls.sheet_names:
                df = pd.read_excel(excel_path, sheet_name=sheet_name)
                df.columns = df.columns.str.strip()
                
                required = ["Pin_Name_For_Upload", "Image_Prompt_For_AI", "Image_name", "Product_ID"]
                if not all(col in df.columns for col in required):
                    logging.warning(f"Skipping sheet {sheet_name} in {excel_file}: Missing columns.")
                    continue
                
                for _, row in df.iterrows():
                    all_tasks.append({"row_data": row, "output_dir": output_dir})
                    if TEST_SINGLE: break
                if TEST_SINGLE: break
        except Exception as e:
            logging.error(f"Error reading {excel_file}: {e}")
            print(f"⚠️ Error reading {excel_file}: {e}")
            
        if TEST_SINGLE and all_tasks: break

    total_tasks = len(all_tasks)
    msg_start = f"📝 Total tasks: {total_tasks}. Output Directory: {GENERATED_CONTENT_FOLDER}"
    print(msg_start)
    logging.info(msg_start)
    
    print(f"\n🚀 Starting processing ({MAX_WORKERS} workers)...")
    start_time = time.time()
    
    results_summary = []
    generation_error_list = []
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [
            executor.submit(
                generate_and_save_image, 
                client, 
                t["row_data"], 
                instruction_text, 
                ASPECT_RATIO, 
                MODEL_NAME, 
                t["output_dir"]
            ) 
            for t in all_tasks
        ]

        for future in tqdm(as_completed(futures), total=total_tasks, unit="img", ncols=100, desc="Generating"):
            res = future.result()
            results_summary.append(res)
            if not res["Success"]:
                res["row_data"]["Generation_Error"] = res["Generation_Error"]
                generation_error_list.append(res["row_data"])
                logging.error(f"Failed: {res['row_data'].get('Product_ID')} - {res['Generation_Error']}")

    end_time = time.time()
    duration = end_time - start_time
    
    success_count = sum(1 for r in results_summary if r["Success"])
    fail_count = len(results_summary) - success_count
    
    print(f"\n" + "="*50)
    print(f"⏱️  Finished in {duration:.2f}s (Avg: {duration/total_tasks if total_tasks else 0:.2f}s/img)")
    print(f"✅ Success: {success_count}")
    print(f"❌ Failed:  {fail_count}")
    print("="*50)
    
    logging.info(f"Finished. Success: {success_count}, Failed: {fail_count}, Duration: {duration:.2f}s")

    if generation_error_list:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        err_file = os.path.join(script_dir, f"Image_Gen_Errors_{timestamp}.xlsx")
        pd.DataFrame(generation_error_list).to_excel(err_file, index=False)
        print(f"💾 Error report saved: {err_file}")
        logging.info(f"Error report saved to: {err_file}")

    print("\n" + "="*50)
    print(f"📂 Images saved to folder: {GENERATED_CONTENT_FOLDER}")
    print(f"📄 Detailed Log saved to:  {log_file_path}")
    print("="*50)
    
    input("\n✅ Work completed. Press Enter to exit program...")