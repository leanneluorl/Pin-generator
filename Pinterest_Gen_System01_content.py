import os
import re
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from dotenv import dotenv_values
from PIL import Image
import pandas as pd
from google import genai
from google.genai.errors import APIError
from jinja2 import Template
import multiprocessing

warnings.filterwarnings("ignore")

import sys
# ... Other imports (dotenv_values, etc.) should be kept before this block if they are needed

# ------------------- Path setup -------------------

# Check if the program is running as a PyInstaller bundled executable
if getattr(sys, 'frozen', False):
    # If frozen (bundled), set base_dir to the directory where the EXE is located (user's external directory)
    base_dir = os.path.dirname(sys.executable)
else:
    # If running as a standard Python script, set base_dir to the script's directory
    base_dir = os.path.dirname(os.path.abspath(__file__))

# Assign the determined base directory to script_dir for all file path constructions
script_dir = base_dir

# Define all file paths using the robust script_dir
ENV_FILE_PATH = os.path.join(script_dir, ".env")

CONFIG_FILE = os.path.join(script_dir, "Pinterest_Affiliate_Data.xlsx")
PRODUCT_FILE = os.path.join(script_dir, "Pinterest_Affiliate_Product.xlsx")
OUTPUT_FOLDER = os.path.join(script_dir, "Generated_Content")
PRODUCT_IMAGE_FOLDER = os.path.join(script_dir, "product_image")

IMAGE_PROMPT_TEMPLATE_FILE = os.path.join(script_dir, "image_prompt_template.txt")
CONTENT_PROMPT_TEMPLATE_FILE = os.path.join(script_dir, "content_prompt_template.txt")

for path in [CONFIG_FILE, PRODUCT_FILE]:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"❌ File not found: {path}")
if not os.path.isdir(PRODUCT_IMAGE_FOLDER):
    print(f"⚠️ Image folder not found: {PRODUCT_IMAGE_FOLDER}. Products without images will be skipped.")

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ------------------- Interactive settings -------------------
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

print("\n--- Loading configuration and API key ---")

env_config = dotenv_values(ENV_FILE_PATH)
GEMINI_API_KEY = env_config.get("GEMINI_API_KEY")

use_mock = False
if not GEMINI_API_KEY:
    print("⚠️ GEMINI_API_KEY not detected in .env file.")
    use_mock = input("   Use simulation mode? (Y/N): ").strip().lower() == 'y'
    client = None
    if not use_mock:
        print("❌ API key missing and simulation mode not selected. Program terminated.")
        exit()
    else:
        print("✓ Running in simulation mode. No API calls will be made.")
else:
    client = genai.Client(api_key=GEMINI_API_KEY)

# ------------------- Helper functions -------------------
def debug_print(tag, text):
    if verbose_debug:
        print(f"\n========== {tag} ==========")
        print(text.strip() if text else "⚠️ No response text")
        print("===========================================\n")


def extract_clean_text(response):
    """Extract safe readable text from Gemini structured output."""
    try:
        if hasattr(response, "text") and response.text:
            return response.text.strip()

        if hasattr(response, "candidates"):
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
        selected_model_series = df_model[df_model['Selection'].astype(str).str.lower().isin(['true','1','yes'])]
        if selected_model_series.empty or len(selected_model_series) > 1:
            raise ValueError("No model selected or multiple models selected in Model_Config.")
        selected_model = selected_model_series.iloc[0]['Model_Name'].strip()

        df_style = pd.read_excel(config_file, sheet_name='Styles_Config', engine='openpyxl').fillna('')
        df_style.columns = df_style.columns.str.strip()
        df_style.set_index('Style_ID', inplace=True)
        df_style.index = df_style.index.astype(str)

        df_process = pd.read_excel(config_file, sheet_name='Process_Config', engine='openpyxl')
        process_sheets = df_process['Product_Sheet_Name'].dropna().astype(str).tolist()

        print(f"✓ Selected AI model: {selected_model}. Sheets to process: {process_sheets}")
        return selected_model, df_style, process_sheets
    except Exception as e:
        print(f"✗ Error loading configuration: {e}")
        return None, None, None


def parse_text_output(text):
    data = {'Pin_Title': "ERROR: Missing Title", 'Pin_Description': "ERROR: Missing Description", 'Pin_Hashtags': "ERROR: Missing Hashtags"}
    if not text or not isinstance(text,str):
        return data
    cleaned = text.strip()

    patterns = {
        'Pin_Title': re.search(r'\[?title\]?\s*[:：]\s*(.*)', cleaned, re.IGNORECASE),
        'Pin_Description': re.search(r'\[?description\]?\s*[:：]\s*(.*)', cleaned, re.IGNORECASE),
        'Pin_Hashtags': re.search(r'\[?hashtags\]?\s*[:：]\s*(.*)', cleaned, re.IGNORECASE)
    }

    for key, match in patterns.items():
        if match:
            val = match.group(1).strip()
            val = re.split(r'\n|\[', val)[0].strip()
            data[key] = val

    return data


# ------------------- Default Templates -------------------
default_image_prompt = """
You are a creative AI image prompt designer.
Create a detailed visual prompt for Pinterest-style imagery.
"""

default_content_prompt = """
You are a Pinterest affiliate marketing copywriter for Western audiences.
Write short and engaging Pinterest content using the following structure:
"""

ensure_template_exists(IMAGE_PROMPT_TEMPLATE_FILE, default_image_prompt)
ensure_template_exists(CONTENT_PROMPT_TEMPLATE_FILE, default_content_prompt)

selected_model, df_style, process_sheets = load_config_and_styles(CONFIG_FILE)
if df_style is None or not process_sheets:
    print("❌ Program terminated: configuration error.")
    exit()

image_prompt_template = load_template(IMAGE_PROMPT_TEMPLATE_FILE)
content_prompt_template = load_template(CONTENT_PROMPT_TEMPLATE_FILE)

current_datetime = datetime.now().strftime("%Y%m%d%H%M")

# ------------------- Output Paths -------------------
output_path_generated = os.path.join(OUTPUT_FOLDER, f"Generated_Content_{current_datetime}.xlsx")
output_path_input_errors = os.path.join(script_dir, f"Input_Errors_{current_datetime}.xlsx")

all_sheet_results = {}
input_error_list = []
generation_error_list = []
missing_image_summary = []
used_titles = set()

# ------------------- Load Product Sheet Names -------------------
try:
    product_excel_file = pd.ExcelFile(PRODUCT_FILE)
    actual_product_sheets = product_excel_file.sheet_names
    print(f"✓ Product file loaded. Found sheets: {actual_product_sheets}")
except Exception as e:
    print(f"❌ Fatal Error: Could not read the product file '{PRODUCT_FILE}'. Error: {e}")
    exit()


# -------- Worker Function for Parallel Processing --------
def process_single_product(product_row, style_row, sheet_name):
    """Worker function executed in parallel for each product-style pair."""
    product_id = str(product_row['Product_ID']).strip()
    style_name = str(style_row['style_Name']).strip()
    print(f"→ Processing Product_ID: {product_id} + Style: {style_name}")
    
    image_name = str(product_row['Image_name']).strip()
    image_path = os.path.join(PRODUCT_IMAGE_FOLDER, image_name)

    try:
        product_image = Image.open(image_path)
    except Exception as e:
        return {"error": f"Failed to load image: {e}", "row": product_row}

    product_info = (
        f"\n--- Product Information ---\n"
        f"Product: {product_row['Product_Name']}\n"
        f"Description: {product_row['Product_desc']}\n"
        f"Category: {product_row['Category']}\n"
        f"Style: {style_row['style_Name']}\n"
        f"Keywords: {product_row['Base_Keywords']}\n"
        f"Mood: {style_row.get('Mood_Descriptor', '')}\n"
        f"Call to Action: {product_row['Call_To_Action']}\n"
    )

    img_prompt = render_template(image_prompt_template) + "\n" + product_info
    content_prompt = render_template(content_prompt_template) + "\n" + product_info

    if use_mock:
        final_img_prompt = "Simulated Image Prompt"
        parsed_output = {'Pin_Title': "Simulated Title", 'Pin_Description': "Simulated Description", 'Pin_Hashtags': "#Simulated #Content"}
        raw_api_response = "Simulation Mode"
    else:
        try:
            resp_img = client.models.generate_content(model=selected_model, contents=[product_image, img_prompt])
            final_img_prompt = extract_clean_text(resp_img)
            debug_print("📸 Gemini Image Prompt Response", final_img_prompt)
        except Exception as e:
            final_img_prompt = f"ERROR: {e}"

        try:
            resp_text = client.models.generate_content(model=selected_model, contents=[product_image, content_prompt])
            raw_api_response = extract_clean_text(resp_text)
            debug_print("📝 Gemini Pinterest Content Response", raw_api_response)

            parsed_output = parse_text_output(raw_api_response)

            has_gen_error = (
                "ERROR:" in parsed_output['Pin_Title'] or
                "ERROR:" in parsed_output['Pin_Description'] or
                "ERROR:" in parsed_output['Pin_Hashtags']
            )

            if has_gen_error:
                return {
                    "error": "Parsing error",
                    "product_id": product_id,
                    "raw": raw_api_response
                }

            MAX_RETRY = 3
            raw_title = parsed_output['Pin_Title'].strip()
            normalized_title = re.sub(r'\W+', '', raw_title.lower())
            retry_count = 0

            while normalized_title in used_titles and retry_count < MAX_RETRY:
                retry_count += 1
                regen_prompt = (
                    "Regenerate a new, unique Pinterest [TITLE] under 60 characters.\n"
                    "It must be catchy and not duplicate previous results.\n\n"
                    f"Previous title: {raw_title}\n"
                    "---\nProduct Info---\n"
                    f"{product_info}"
                )

                try:
                    resp_retry = client.models.generate_content(model=selected_model, contents=[product_image, regen_prompt])
                    new_text = extract_clean_text(resp_retry)
                    new_data = parse_text_output(new_text)
                    raw_title = new_data.get('Pin_Title', raw_title).strip()
                    normalized_title = re.sub(r'\W+', '', raw_title.lower())
                except Exception:
                    break

            parsed_output['Pin_Title'] = raw_title
            used_titles.add(normalized_title)

        except Exception as e:
            return {"error": f"API Failed: {e}", "product_id": product_id}

    raw_hashtags = parsed_output.get('Pin_Hashtags', '')
    keywords_list = re.findall(r'#(\w+)', raw_hashtags)
    pin_keywords = ', '.join(keywords_list)

    return {
        'Pin_Name_For_Upload': f"{product_id}_{style_row['style_Name']}".replace(' ','_'),
        'Affiliate_Link': product_row['Affiliate_Link'],
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


# ------------------- Processing Sheets -------------------
cpu_count = multiprocessing.cpu_count()
max_workers = 5 if cpu_count >= 8 else 3
print(f"\n⚙ Using auto-parallel mode → {max_workers} threads\n")

for sheet_name in process_sheets:

    if sheet_name not in actual_product_sheets:
        print(f"\n⚠️ Skipping sheet '{sheet_name}' (not found in product file)")
        continue

    print(f"\n--- Processing sheet: {sheet_name} ---")

    df_products = pd.read_excel(PRODUCT_FILE, sheet_name=sheet_name, engine='openpyxl').fillna('')
    if 'Pinterest_Angle' in df_products.columns:
        df_products.rename(columns={'Pinterest_Angle':'Product_desc'}, inplace=True)

    for col in REQUIRED_PRODUCT_COLS:
        if col not in df_products.columns:
            df_products[col] = pd.NA

    job_list = []

    for idx, product_row in df_products.iterrows():
        missing_cols = [col for col in REQUIRED_PRODUCT_COLS if pd.isna(product_row[col]) or str(product_row[col]).strip() == '']

        if missing_cols:
            error_details = product_row.to_dict()
            error_details['Error_Message'] = f"Missing required fields: {', '.join(missing_cols)}"
            error_details['Source_Product_Sheet'] = sheet_name
            input_error_list.append(error_details)
            continue

        image_path = os.path.join(PRODUCT_IMAGE_FOLDER, product_row['Image_name'])
        if not os.path.isfile(image_path):
            error_details = product_row.to_dict()
            error_details['Error_Message'] = f"Image file not found: {product_row['Image_name']}"
            error_details['Source_Product_Sheet'] = sheet_name
            input_error_list.append(error_details)
            continue

        for style_id, style_row in df_style.iterrows():
            job_list.append((product_row, style_row, sheet_name))
            if test_single:
                break
        if test_single:
            break

    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_single_product, row, style, sheet_name): (row, style)
                   for row, style, sheet_name in job_list}

        for future in as_completed(futures):
            result = future.result()
            results.append(result)

    df_result = pd.DataFrame([r for r in results if isinstance(r, dict) and 'error' not in r])
    all_sheet_results[sheet_name] = df_result

    generation_error_list.extend([r for r in results if 'error' in r])

# ------------------- Save Outputs -------------------
if all_sheet_results or generation_error_list:
    with pd.ExcelWriter(output_path_generated, engine='openpyxl') as writer:
        for sheet_name, df_result in all_sheet_results.items():
            if not df_result.empty:
                df_result.to_excel(writer, sheet_name=sheet_name, index=False)

        if generation_error_list:
            pd.DataFrame(generation_error_list).to_excel(writer, sheet_name='Generation_Errors', index=False)

    print(f"\n✓ Output saved: {output_path_generated}")

if input_error_list:
    pd.DataFrame(input_error_list).to_excel(output_path_input_errors, index=False)
    print(f"⚠ Input errors logged: {output_path_input_errors}")
