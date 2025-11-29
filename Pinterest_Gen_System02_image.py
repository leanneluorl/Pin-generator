import os
import time
import base64
from io import BytesIO
from PIL import Image
import pandas as pd
from google import genai
from google.genai import types
from dotenv import dotenv_values
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed # 引入並行處理模組

# 設定並行處理的最大執行緒數
MAX_WORKERS = 3

# ------------------- Path setup -------------------
script_dir = os.path.dirname(os.path.abspath(__file__))
ENV_FILE_PATH = os.path.join(script_dir, ".env")

GENERATED_CONTENT_FOLDER = os.path.join(script_dir, "Generated_Content")
PRODUCT_IMAGE_FOLDER = os.path.join(script_dir, "product_image")

INSTRUCTION_FILE = os.path.join(script_dir, "image_generation_instruction.txt")

# ------------------- Default instruction template -------------------
default_instruction = """
Use the provided product image as the main object in the composition.
Ensure the final image is Pinterest-ready: visually appealing, clean, and photorealistic.

Instructions:
- Keep the product clear and proportional to the original reference image.
- Remove any text, watermarks, or annotations.
- Create a realistic scene that complements the product style.
- Maintain ultra-high quality, cinematic lighting, and realistic texture.
- The final image should have a Pinterest aspect ratio and no measurement lines or labels.
"""

def ensure_template_exists(path, default_text):
    """Create a default text file if missing."""
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(default_text.strip())
        print(f"🆕 Created default instruction file: {os.path.basename(path)}")

def load_instruction_text():
    ensure_template_exists(INSTRUCTION_FILE, default_instruction)
    with open(INSTRUCTION_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()

# ------------------- API Call Worker Function -------------------

def generate_and_save_image(client, row_data, instruction_text, ASPECT_RATIO, MODEL_NAME, output_dir):
    """
    單一工作單元：負責圖片生成和儲存。
    回傳一個字典，包含處理結果或錯誤信息。
    """
    pin_name = str(row_data["Pin_Name_For_Upload"]).strip()
    image_prompt = str(row_data["Image_Prompt_For_AI"]).strip()
    image_name = str(row_data["Image_name"]).strip()
    product_id = str(row_data["Product_ID"]).strip()
    
    # 建立回傳數據的基礎結構
    result = {"row_data": row_data.to_dict(), "Generation_Error": None, "Success": False}
    
    # --- 1. 檢查 Image Prompt ---
    if not image_prompt or image_prompt.lower() == 'nan' or image_prompt.lower().startswith('error'):
        result["Generation_Error"] = "❌ Missing or invalid Image Prompt ('Image_Prompt_For_AI' is empty or error code)."
        return result

    # --- 2. 檢查原始產品圖片 ---
    image_path = os.path.join(PRODUCT_IMAGE_FOLDER, image_name)
    if not os.path.isfile(image_path):
        result["Generation_Error"] = f"❌ Missing product image file: {image_name}"
        return result

    try:
        product_image = Image.open(image_path)
    except Exception as e:
        result["Generation_Error"] = f"❌ Failed to open/load product image {image_name}. Error: {e}"
        return result

    # --- 3. API 呼叫設定 ---
    final_prompt = f"{image_prompt}\n\n{instruction_text}"
    contents = [final_prompt, product_image]

    generate_config = types.GenerateContentConfig(
        response_modalities=["IMAGE", "TEXT"],
        image_config=types.ImageConfig(aspect_ratio=ASPECT_RATIO)
    )

    try:
        print(f"🧠 Generating image for: {pin_name} (Product_ID: {product_id}) ...")
        resp = client.models.generate_content(
            model=MODEL_NAME,
            contents=contents,
            config=generate_config
        )
    except Exception as e:
        result["Generation_Error"] = f"API error during generation: {e}"
        return result

    # --- 4. 儲存生成的圖片 ---
    image_saved = False
    if resp.candidates and resp.candidates[0].content.parts:
        for part in resp.candidates[0].content.parts:
            if part.inline_data:
                mime_type = getattr(part.inline_data, "mime_type", "")
                if mime_type.startswith("image/"):
                    try:
                        img_bytes = base64.b64decode(part.inline_data.data)
                        img = Image.open(BytesIO(img_bytes))
                        safe_name = "".join(c if c.isalnum() else "_" for c in pin_name)
                        filename = f"{safe_name}.png"
                        save_path = os.path.join(output_dir, filename)
                        img.save(save_path)
                        image_saved = True
                        print(f"✅ Image saved: {save_path}")
                    except Exception as e:
                        result["Generation_Error"] = f"⚠️ Failed to save image to disk (Product_ID: {product_id}): {e}"
                        return result
                    
    if not image_saved:
        result["Generation_Error"] = "Invalid, empty, or failed to save generated image (API returned no valid data)."
        return result
    
    result["Success"] = True
    return result

# ------------------- Main Execution -------------------

# ------------------- User input settings -------------------
print("\n=== Pinterest Image Generator Configuration ===")
TEST_SINGLE = input("Run in single test mode? (Y/N): ").strip().lower() == 'y'
ASPECT_RATIO = input("Enter desired image aspect ratio (default 2:3): ").strip() or "2:3"
MODEL_NAME = input("Enter Gemini model name (default gemini-2.5-flash-image): ").strip() or "gemini-2.5-flash-image"

# ------------------- Load API key -------------------
print("\n--- Loading configuration and API key ---")
# Get GEMINI_API_KEY from .env 
env_config = dotenv_values(ENV_FILE_PATH)
GEMINI_API_KEY = env_config.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("🛑 Missing GEMINI_API_KEY in .env file.")
    exit()
client = genai.Client(api_key=GEMINI_API_KEY)

# ------------------- Load instruction text -------------------
instruction_text = load_instruction_text()

# ------------------- Locate Excel files -------------------
excel_files = [f for f in os.listdir(GENERATED_CONTENT_FOLDER) if f.lower().endswith(".xlsx")]
if not excel_files:
    print(f"🛑 No Excel files found in {GENERATED_CONTENT_FOLDER}")
    exit()

all_tasks = []
all_results = []
missing_images = []
generation_error_list = []

# ------------------- Prepare all tasks -------------------
print("\n--- Preparing all image generation tasks ---")
for excel_file in excel_files:
    excel_path = os.path.join(GENERATED_CONTENT_FOLDER, excel_file)
    output_dir = os.path.join(GENERATED_CONTENT_FOLDER, os.path.splitext(excel_file)[0])
    os.makedirs(output_dir, exist_ok=True)

    xls = pd.ExcelFile(excel_path)
    for sheet_name in xls.sheet_names:
        df = pd.read_excel(excel_path, sheet_name=sheet_name)
        df.columns = df.columns.str.strip()

        required_cols = ["Pin_Name_For_Upload", "Image_Prompt_For_AI", "Image_name", "Product_ID"]
        if not all(col in df.columns for col in required_cols):
            print(f"⚠️ Sheet {sheet_name} in {excel_file} missing required columns {required_cols}, skipping.")
            continue
        
        for idx, row in df.iterrows():
            # 將每個 row 及其必要的上下文作為一個任務加入列表
            task = {
                "row_data": row,
                "output_dir": output_dir
            }
            all_tasks.append(task)
            
            if TEST_SINGLE:
                break
        if TEST_SINGLE:
            break
    if TEST_SINGLE:
        break

print(f"📝 Total tasks prepared: {len(all_tasks)}")

# ------------------- Execute tasks concurrently -------------------
print(f"\n🚀 Starting concurrent image generation with {MAX_WORKERS} workers...")
start_time = time.time()

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    # 提交所有任務到執行緒池
    futures = [
        executor.submit(
            generate_and_save_image, 
            client, 
            task["row_data"], 
            instruction_text, 
            ASPECT_RATIO, 
            MODEL_NAME, 
            task["output_dir"]
        ) 
        for task in all_tasks
    ]

    # 處理已完成的任務
    for future in as_completed(futures):
        try:
            result = future.result()
            all_results.append(result)
            
            if not result["Success"]:
                error_message = result["Generation_Error"]
                error_data = result["row_data"]
                error_data["Generation_Error"] = error_message
                generation_error_list.append(error_data)
                
                # 特殊處理圖片缺失錯誤
                if "Missing product image file" in error_message or "Failed to open/load product image" in error_message:
                    missing_images.append(error_data["Product_ID"])

        except Exception as e:
            # 捕獲執行緒層面的意外錯誤
            print(f"❌ An unexpected error occurred in a worker thread: {e}")


end_time = time.time()
print(f"\n⏱️ Concurrent processing finished in {end_time - start_time:.2f} seconds.")

# ------------------- Summary -------------------
if missing_images:
    # 使用 set 避免重複的 Product_ID
    unique_missing = sorted(list(set(missing_images)))
    print("\n⚠️ Missing images for the following Product_IDs (See report for details):")
    for pid in unique_missing:
        print(f" - {pid}")
else:
    print("\n✅ All product image files were located.")

# ------------------- Write Error Output -------------------
if generation_error_list:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path_errors = os.path.join(script_dir, f"Image_Gen_Errors_{timestamp}.xlsx")
    
    try:
        # 使用收集到的錯誤列表建立 DataFrame
        df_gen_errors = pd.DataFrame(generation_error_list)
        df_gen_errors['Error_Time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 寫入 Excel
        with pd.ExcelWriter(output_path_errors, engine='openpyxl') as writer:
            df_gen_errors.to_excel(writer, sheet_name='Image_Generation_Failures', index=False)
            
        print(f"\n🚨 {len(df_gen_errors)} image generation errors found (API or I/O failure).")
        print(f"💾 Detailed error report saved to: {output_path_errors}")
    except Exception as e:
        print(f"❌ CRITICAL: Failed to write image error report: {e}")
else:
    print("\n✅ No image generation errors reported.")
# ----------------------------------------------------------------------

print("\n--- All tasks completed ---")