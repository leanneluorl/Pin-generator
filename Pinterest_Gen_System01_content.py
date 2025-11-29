import os
import re
import time
import warnings
import random
import sys  # 用於捕捉系統錯誤
from concurrent.futures import ThreadPoolExecutor, as_completed
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

# ------------------- Path setup -------------------
script_dir = os.path.dirname(os.path.abspath(__file__))
ENV_FILE_PATH = os.path.join(script_dir, ".env")

CONFIG_FILE = os.path.join(script_dir, "Pinterest_Affiliate_Data.xlsx")
PRODUCT_FILE = os.path.join(script_dir, "Pinterest_Affiliate_Product.xlsx")
OUTPUT_FOLDER = os.path.join(script_dir, "Generated_Content")
PRODUCT_IMAGE_FOLDER = os.path.join(script_dir, "product_image")

IMAGE_PROMPT_TEMPLATE_FILE = os.path.join(script_dir, "image_prompt_template.txt")
CONTENT_PROMPT_TEMPLATE_FILE = os.path.join(script_dir, "content_prompt_template.txt")

# Check Paths
for path in [CONFIG_FILE, PRODUCT_FILE]:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"❌ File not found: {path}")

if not os.path.isdir(PRODUCT_IMAGE_FOLDER):
    print(f"⚠️ Image folder not found: {PRODUCT_IMAGE_FOLDER}. Products without images will be skipped.")

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ------------------- Interactive settings -------------------
print("--- Configuration Setup ---")
test_single = input("Run single test mode? (Y/N): ").strip().lower() == 'y'
verbose_debug = input("Enable detailed debug output? (Y/N): ").strip().lower() == 'y'
require_affiliate_link = input("Is 'Affiliate_Link' a required field? (Y/N): ").strip().lower() == 'y'

BASE_REQUIRED_COLS = ['Product_ID', 'Product_Name', 'Image_name', 'Product_desc']
REQUIRED_PRODUCT_COLS = BASE_REQUIRED_COLS.copy()

if require_affiliate_link:
    REQUIRED_PRODUCT_COLS.append('Affiliate_Link')
    print("✓ 'Affiliate_Link' will be validated as a required field.")
else:
    print("✓ 'Affiliate_Link' will be treated as an optional field.")

# ------------------- API Setup -------------------
print("\n--- Loading configuration and API key ---")
env_config = dotenv_values(ENV_FILE_PATH)
GEMINI_API_KEY = env_config.get("GEMINI_API_KEY")

use_mock = False
client = None

if not GEMINI_API_KEY:
    print("⚠️ GEMINI_API_KEY not detected in .env file.")
    use_mock = input("   Use simulation mode? (Y/N): ").strip().lower() == 'y'
    if not use_mock:
        print("❌ API key missing and simulation mode not selected. Program terminated.")
        exit()
    else:
        print("✓ Running in simulation mode. No API calls will be made.")
else:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"❌ Failed to initialize Gemini Client: {e}")
        exit()

# ------------------- Helper functions -------------------
def debug_print(tag, text):
    if verbose_debug:
        print(f"\n========== {tag} ==========")
        print(text.strip() if text else "⚠️ No response text")
        print("===========================================\n")

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
        print(f"🆕 Created default template: {os.path.basename(path)}")

def load_template(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def render_template(template_str):
    return Template(template_str).render()

def load_config_and_styles(config_file):
    try:
        df_model = pd.read_excel(config_file, sheet_name='Model_Config')
        df_model.columns = df_model.columns.str.strip()

        if verbose_debug:
            print("\n🔍 [DEBUG] Model Config Raw Data:")
            print(df_model[['Model_Name', 'Selection', 'Max_Workers']].head())

        def is_selected(val):
            s = str(val).strip().lower()
            return s in ['true', '1', 'yes', '1.0', 'y', 'on']

        selected_model_series = df_model[df_model['Selection'].apply(is_selected)]
        
        selected_model = "gemini-2.0-flash-exp"
        max_workers = 3
        delay_seconds = 0

        if selected_model_series.empty:
            print(f"⚠️ No model selected. Defaulting to '{selected_model}', Workers: {max_workers}")
        else:
            if len(selected_model_series) > 1:
                print("⚠️ Multiple models selected. Using the first one.")

            row = selected_model_series.iloc[0]
            selected_model = str(row['Model_Name']).strip()
            if 'Max_Workers' in row and pd.notna(row['Max_Workers']):
                try:
                    max_workers = int(float(row['Max_Workers']))
                except ValueError:
                    max_workers = 1
            if 'Rate_Limit_Delay' in row and pd.notna(row['Rate_Limit_Delay']):
                try:
                    delay_seconds = int(float(row['Rate_Limit_Delay']))
                except ValueError:
                    delay_seconds = 0

        df_style = pd.read_excel(config_file, sheet_name='Styles_Config', engine='openpyxl').fillna('')
        df_style.columns = df_style.columns.str.strip()
        df_style.set_index('Style_ID', inplace=True)
        df_style.index = df_style.index.astype(str)

        df_process = pd.read_excel(config_file, sheet_name='Process_Config', engine='openpyxl')
        process_sheets = df_process['Product_Sheet_Name'].dropna().astype(str).tolist()

        print(f"✓ Selected Model: {selected_model}")
        print(f"✓ Configured Workers: {max_workers}")
        print(f"✓ Configured Delay: {delay_seconds} seconds")
        print(f"✓ Sheets to process: {process_sheets}")
        
        return selected_model, df_style, process_sheets, max_workers, delay_seconds

    except Exception as e:
        print(f"✗ Error loading configuration: {e}")
        return None, None, None, 1, 0

def parse_text_output(text):
    data = {'Pin_Title': "ERROR", 'Pin_Description': "ERROR", 'Pin_Hashtags': "ERROR"}
    if not text or not isinstance(text, str): return data
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

# ------------------- Templates & Config -------------------
default_image_prompt = """
You are a creative AI image prompt designer.
Create a detailed visual prompt for Pinterest-style imagery.
"""

default_content_prompt = """
You are a Pinterest affiliate marketing copywriter.
Write engaging Pinterest content.
"""

ensure_template_exists(IMAGE_PROMPT_TEMPLATE_FILE, default_image_prompt)
ensure_template_exists(CONTENT_PROMPT_TEMPLATE_FILE, default_content_prompt)

# --- LOAD CONFIGURATION ---
config_result = load_config_and_styles(CONFIG_FILE)
if config_result[0] is None:
    print("❌ Program terminated: configuration error.")
    exit()

selected_model, df_style, process_sheets, config_max_workers, config_delay = config_result

image_prompt_template = load_template(IMAGE_PROMPT_TEMPLATE_FILE)
content_prompt_template = load_template(CONTENT_PROMPT_TEMPLATE_FILE)

current_datetime = datetime.now().strftime("%Y%m%d%H%M")
output_path_generated = os.path.join(OUTPUT_FOLDER, f"Generated_Content_{current_datetime}.xlsx")
output_path_input_errors = os.path.join(script_dir, f"Input_Errors_{current_datetime}.xlsx")

# 初始化全域變數 (保證在 finally 區塊能被讀取)
all_sheet_results = {}
input_error_list = []
generation_error_list = []
used_titles = set()

try:
    product_excel_file = pd.ExcelFile(PRODUCT_FILE)
    actual_product_sheets = product_excel_file.sheet_names
    print(f"✓ Product file loaded. Found sheets: {actual_product_sheets}")
except Exception as e:
    print(f"❌ Fatal Error: Could not read the product file '{PRODUCT_FILE}'. Error: {e}")
    exit()

# ------------------- Auto-Retry API Wrapper -------------------
def call_api_with_retry(api_func, *args, max_retries=5, initial_wait=10, **kwargs):
    attempt = 0
    while attempt <= max_retries:
        try:
            return api_func(*args, **kwargs)
        except Exception as e:
            error_str = str(e)
            # 偵測 Quota 錯誤
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "quota" in error_str.lower():
                attempt += 1
                if attempt > max_retries:
                    raise e
                wait_time = (initial_wait * (2 ** (attempt - 1))) + random.uniform(1, 5)
                print(f"⚠️ API Quota Hit (429). Retrying in {wait_time:.1f}s... (Attempt {attempt}/{max_retries})")
                time.sleep(wait_time)
            else:
                raise e

# ------------------- Worker Function -------------------
def process_single_product(product_row, style_row, sheet_name):
    product_id = str(product_row.get('Product_ID', 'Unknown')).strip()
    product_name = str(product_row.get('Product_Name', 'Unknown')).strip()
    style_name = str(style_row.get('style_Name', 'Default')).strip()
    
    # 簡化 Log，只顯示開始
    print(f"→ Start: {product_id} [{style_name}]")
    
    error_context = {
        "Source_Product_Sheet": sheet_name,
        "Product_ID": product_id,
        "Product_Name": product_name,
        "Style_Name": style_name,
        "Error_Message": "",
        "Raw_Response": ""
    }

    image_name = str(product_row.get('Image_name', '')).strip()
    image_path = os.path.join(PRODUCT_IMAGE_FOLDER, image_name)

    try:
        if not image_name or not os.path.isfile(image_path):
            raise FileNotFoundError(f"Image not found: {image_name}")
        product_image = Image.open(image_path)
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

    img_prompt = render_template(image_prompt_template) + "\n" + product_info
    content_prompt = render_template(content_prompt_template) + "\n" + product_info + format_instructions

    if use_mock:
        final_img_prompt = "Simulated Image Prompt"
        parsed_output = {'Pin_Title': f"Simulated Title {product_id}", 'Pin_Description': "Simulated Desc", 'Pin_Hashtags': "#Simulated"}
        raw_api_response = "Simulation Mode"
        if config_delay > 0: time.sleep(config_delay)
    else:
        try:
            # 1. Generate Image Prompt
            try:
                resp_img = call_api_with_retry(
                    client.models.generate_content, 
                    model=selected_model, 
                    contents=[product_image, img_prompt]
                )
                final_img_prompt = extract_clean_text(resp_img)
            except Exception as e:
                final_img_prompt = f"IMAGE PROMPT ERROR: {str(e)}"

            # 2. Generate Content
            resp_text = call_api_with_retry(
                client.models.generate_content,
                model=selected_model,
                contents=[product_image, content_prompt]
            )
            raw_api_response = extract_clean_text(resp_text)
            
            parsed_output = parse_text_output(raw_api_response)

            has_gen_error = ("ERROR:" in parsed_output['Pin_Title'] or "ERROR:" in parsed_output['Pin_Description'])

            if has_gen_error:
                error_context['Error_Message'] = "Parsing Error (Content missing or wrong format)"
                error_context['Raw_Response'] = raw_api_response
                return {"error": True, "details": error_context}

            # Retry Logic for Duplicate Titles
            MAX_RETRY = 3
            raw_title = parsed_output['Pin_Title'].strip()
            normalized_title = re.sub(r'\W+', '', raw_title.lower())
            retry_count = 0
            while normalized_title in used_titles and retry_count < MAX_RETRY:
                retry_count += 1
                regen_prompt = f"Regenerate unique Pinterest [Title]. Do not use: {raw_title}\nFormat: [Title]: New Title"
                try:
                    resp_retry = call_api_with_retry(
                        client.models.generate_content,
                        model=selected_model,
                        contents=[product_image, regen_prompt]
                    )
                    new_data = parse_text_output(extract_clean_text(resp_retry))
                    if "ERROR" not in new_data['Pin_Title']:
                        raw_title = new_data['Pin_Title']
                        normalized_title = re.sub(r'\W+', '', raw_title.lower())
                except Exception: break
            
            used_titles.add(normalized_title)
            parsed_output['Pin_Title'] = raw_title

            # Configured Delay
            if config_delay > 0:
                print(f"⏳ Sleeping {config_delay}s...")
                time.sleep(config_delay)

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
# 🔥 核心執行區塊 (包含 Try-Finally 強制存檔機制) 🔥
# =======================================================
print(f"\n⚙ Starting execution with {config_max_workers} workers (Auto-Retry enabled).\n")

try:
    for sheet_name in process_sheets:
        if sheet_name not in actual_product_sheets:
            print(f"\n⚠️ Skipping sheet '{sheet_name}' (not found in product file)")
            continue

        print(f"\n--- Processing sheet: {sheet_name} ---")

        df_products = pd.read_excel(PRODUCT_FILE, sheet_name=sheet_name, engine='openpyxl').fillna('')
        if 'Pinterest_Angle' in df_products.columns:
            df_products.rename(columns={'Pinterest_Angle':'Product_desc'}, inplace=True)

        job_list = []
        for idx, product_row in df_products.iterrows():
            missing_cols = [col for col in REQUIRED_PRODUCT_COLS if col not in df_products.columns or pd.isna(product_row[col]) or str(product_row[col]).strip() == '']
            if missing_cols:
                error_details = {'Source_Product_Sheet': sheet_name, 'Product_ID': str(product_row.get('Product_ID', 'N/A')), 'Error_Message': f"Missing fields: {missing_cols}"}
                input_error_list.append(error_details)
                continue

            for style_id, style_row in df_style.iterrows():
                job_list.append((product_row, style_row, sheet_name))
                if test_single: break
            if test_single: break

        results = []
        
        with ThreadPoolExecutor(max_workers=config_max_workers) as executor:
            futures = {executor.submit(process_single_product, row, style, sheet): (row, style)
                    for row, style, sheet in job_list}

            completed_count = 0
            total_count = len(futures)

            for future in as_completed(futures):
                try:
                    result = future.result()
                    results.append(result)
                    completed_count += 1
                    # 顯示進度，讓你確認它還活著
                    if completed_count % 1 == 0:
                        print(f"   [Progress] {completed_count}/{total_count} done.")
                except Exception as e:
                    print(f"❌ Thread Error: {e}")

        success_data = [r for r in results if isinstance(r, dict) and not r.get('error')]
        error_data = [r['details'] for r in results if isinstance(r, dict) and r.get('error')]

        if success_data:
            df_result = pd.DataFrame(success_data)
            cols_order = ['Pin_Name_For_Upload', 'Affiliate_Link', 'Image_name', 'Image_Prompt_For_AI', 'Pin_Title', 'Pin_Description', 'Pin_Keywords', 'Generated_Date', 'Source_Product_Sheet', 'Product_ID', 'Applied_Style_ID', 'Style_Name']
            final_cols = [c for c in cols_order if c in df_result.columns]
            all_sheet_results[sheet_name] = df_result[final_cols]
        
        if error_data:
            generation_error_list.extend(error_data)

except KeyboardInterrupt:
    print("\n\n🛑 User interrupted! Saving collected data before exiting...")
except Exception as e:
    print(f"\n\n❌ Critical Error: {e}. Saving collected data before crashing...")
finally:
    # ------------------- Save Outputs (保命區塊) -------------------
    print("\n--- Saving Results (Data Rescue) ---")

    if all_sheet_results or generation_error_list:
        try:
            # 確保檔案沒有被打開，若打開則存成新檔名
            try:
                with pd.ExcelWriter(output_path_generated, engine='openpyxl') as writer:
                    for sheet_name, df_result in all_sheet_results.items():
                        if not df_result.empty:
                            df_result.to_excel(writer, sheet_name=sheet_name, index=False)
                            print(f"✓ Sheet saved: {sheet_name} ({len(df_result)} rows)")
                    
                    if generation_error_list:
                        pd.DataFrame(generation_error_list).to_excel(writer, sheet_name='Generation_Errors', index=False)
                        print(f"⚠ Generation Errors saved ({len(generation_error_list)} rows)")
                print(f"✓ Full Report saved to: {output_path_generated}")
            except PermissionError:
                # 萬一你忘記關閉 Excel，它會嘗試換個檔名存檔，而不是直接報錯
                new_path = output_path_generated.replace(".xlsx", "_RESCUED.xlsx")
                print(f"⚠️ Original file is open! Saving to: {new_path}")
                with pd.ExcelWriter(new_path, engine='openpyxl') as writer:
                    for sheet_name, df_result in all_sheet_results.items():
                        if not df_result.empty:
                            df_result.to_excel(writer, sheet_name=sheet_name, index=False)
                    if generation_error_list:
                        pd.DataFrame(generation_error_list).to_excel(writer, sheet_name='Generation_Errors', index=False)
                print(f"✓ Rescued Data saved to: {new_path}")

        except Exception as e:
            print(f"❌ Error saving output Excel: {e}")

    if input_error_list:
        try:
            pd.DataFrame(input_error_list).to_excel(output_path_input_errors, index=False)
            print(f"⚠ Input Errors logged to: {output_path_input_errors}")
        except Exception as e:
            print(f"❌ Error saving input errors: {e}")

    print("\n--- Execution Finished ---")