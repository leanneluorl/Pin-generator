import PyInstaller.__main__
import shutil
import os
import sys

# =======================================================
# ⚙️ 設定區域 (Configuration)
# =======================================================

# 存放 Sample 檔案的實體資料夾 (您的電腦上存放 sample 的地方)
SAMPLE_DIR_NAME = "sample_files"

# 資源設定清單
# 格式: ("來源類型", "來源檔名", "打包進EXE後的檔名")
# 來源類型: 
#   "sample" -> 從 sample_files 資料夾抓，通常用於 Excel
#   "root"   -> 從專案根目錄抓，通常用於 txt
#   "generate_env" -> 自動生成空檔案
SCRIPT_CONFIG = {
    # 🟢 1. Image Generator (Generic_Batch_Image_Generator.py)
    # 專屬檔案：image_generation_instruction.txt
    "image": { 
        "resources": [
            ("sample", "Config_Data-sample.xlsx", "Config_Data.xlsx"), 
            ("root",   "image_generation_instruction.txt", "image_generation_instruction.txt"),
            ("generate_env", None, ".env")
        ],
        "folders": [],     
        "create_dirs": ["Generated_Images", "Logs"] # Image Generator 需要的資料夾
    },
    
    # 🔵 2. Content Generator (Pinterest_Gen_System01_content.py)
    # 專屬檔案：Pinterest_Affiliate_Product.xlsx, image_prompt_template.txt, content_prompt_template.txt
    "content": {
        "resources": [
            ("sample", "Config_Data-sample.xlsx", "Config_Data.xlsx"),
            ("sample", "Pinterest_Affiliate_Product-Sample.xlsx", "Pinterest_Affiliate_Product.xlsx"),
            ("root",   "image_prompt_template.txt", "image_prompt_template.txt"), 
            ("root",   "content_prompt_template.txt", "content_prompt_template.txt"),
            ("generate_env", None, ".env") 
        ],
        "folders": [], 
        "create_dirs": ["Generated_Content", "ref_image", "Logs"] # Content Generator 需要的資料夾
    }
}

# 全域變數
SCRIPT_NAME = ""
EXE_NAME = ""
CURRENT_RESOURCE_CONFIG = {}
TEMP_BUILD_DIR = "_build_assets_temp"

# =======================================================
# 🛠️ 核心函式
# =======================================================

def prepare_safe_assets():
    """準備資源：將所有需要的檔案複製到暫存區，並改名為正式名稱"""
    if os.path.exists(TEMP_BUILD_DIR):
        shutil.rmtree(TEMP_BUILD_DIR)
    os.makedirs(TEMP_BUILD_DIR)
    
    print(f"\n🛡️  準備打包資源至暫存區: {TEMP_BUILD_DIR}")
    
    resources = CURRENT_RESOURCE_CONFIG.get("resources", [])
    paths_for_pyinstaller = [] 

    for source_type, source_name, target_name in resources:
        destination_path = os.path.join(TEMP_BUILD_DIR, target_name)
        
        try:
            if source_type == "sample":
                source_path = os.path.join(SAMPLE_DIR_NAME, source_name)
                if os.path.exists(source_path):
                    shutil.copy2(source_path, destination_path)
                    print(f"   📂 [Sample] {source_name} -> 打包為 {target_name}")
                else:
                    print(f"   ❌ 錯誤：找不到 Sample 檔案 {source_path}")
                    continue
                    
            elif source_type == "root":
                if os.path.exists(source_name):
                    shutil.copy2(source_name, destination_path)
                    print(f"   📄 [File] {source_name} -> 打包為 {target_name}")
                else:
                    # 這是關鍵檢查，確保 Image 不會打包到 Content 的檔案，反之亦然
                    print(f"   ⚠️ 警告：找不到檔案 {source_name} (請確認此檔案是否屬於此程式)")
                    continue
                    
            elif source_type == "generate_env":
                with open(destination_path, "w", encoding="utf-8") as f:
                    f.write("GEMINI_API_KEY=\n") 
                print(f"   🔒 [Gen] 生成預設 .env -> 打包為 .env")

            # 告訴 PyInstaller：把這個暫存檔案，放到 EXE 內部的根目錄 (.)
            paths_for_pyinstaller.append((destination_path, "."))
            
        except Exception as e:
            print(f"   ❌ 處理失敗 ({target_name}): {e}")

    return paths_for_pyinstaller

def cleanup_temp_assets():
    if os.path.exists(TEMP_BUILD_DIR):
        try: shutil.rmtree(TEMP_BUILD_DIR)
        except: pass

def select_target_script():
    global SCRIPT_NAME, EXE_NAME, CURRENT_RESOURCE_CONFIG
    # 排除 build.py 自己
    files = [f for f in os.listdir('.') if f.endswith('.py') and f != os.path.basename(__file__)]
    
    if not files:
        print("❌ 錯誤：找不到 .py 檔案！")
        sys.exit(1)

    print("\n==========================================")
    print("📂 請選擇要打包的程式：")
    for index, file in enumerate(files):
        print(f"  [{index + 1}] {file}")
    print("==========================================")
    
    while True:
        try:
            selection = input("👉 請輸入編號: ").strip()
            idx = int(selection) - 1
            if 0 <= idx < len(files):
                SCRIPT_NAME = files[idx]
                EXE_NAME = os.path.splitext(SCRIPT_NAME)[0]
                
                # 🔥 自動判斷模式 (根據檔名)
                s_lower = SCRIPT_NAME.lower()
                
                # 如果檔名包含 content (例如 Pinterest_Gen_System01_content.py)
                if "content" in s_lower:
                    print(f"💡 識別模式: Content Generator (Pinterest)")
                    CURRENT_RESOURCE_CONFIG = SCRIPT_CONFIG["content"]
                
                # 如果檔名包含 image (例如 Generic_Batch_Image_Generator.py)
                elif "image" in s_lower:
                    print(f"💡 識別模式: Image Generator (Generic)")
                    CURRENT_RESOURCE_CONFIG = SCRIPT_CONFIG["image"]
                
                else:
                    print("⚠️ 無法識別模式，預設使用 Content 設定")
                    CURRENT_RESOURCE_CONFIG = SCRIPT_CONFIG["content"]
                break
            else: print("❌ 無效編號")
        except ValueError: print("❌ 請輸入數字")

def build_exe(resource_paths):
    print(f"\n📦 開始 PyInstaller 打包: {SCRIPT_NAME} ...")
    
    pyinstaller_args = [
        SCRIPT_NAME,
        f'--name={EXE_NAME}',
        '--onefile',
        '--console',
        '--clean',
        '--noconfirm',
        '--hidden-import=pandas',
        '--hidden-import=openpyxl',
        '--hidden-import=PIL',
        '--hidden-import=google.genai',
        '--hidden-import=dotenv',
        '--hidden-import=jinja2',
    ]
    
    separator = ';' if os.name == 'nt' else ':'
    for real_path, internal_dest in resource_paths:
        add_data_arg = f'{real_path}{separator}{internal_dest}'
        pyinstaller_args.append(f'--add-data={add_data_arg}')
    
    PyInstaller.__main__.run(pyinstaller_args)

def post_build_setup():
    dist_dir = os.path.join("dist")
    final_output_folder = os.path.join(dist_dir, f"{EXE_NAME}_Folder")
    
    if os.path.exists(final_output_folder):
        shutil.rmtree(final_output_folder)
    os.makedirs(final_output_folder)

    # 移動 EXE
    exe_src = os.path.join(dist_dir, f"{EXE_NAME}.exe")
    if os.path.exists(exe_src):
        shutil.move(exe_src, os.path.join(final_output_folder, f"{EXE_NAME}.exe"))
    
    # 建立該程式專屬的空資料夾
    for folder in CURRENT_RESOURCE_CONFIG.get("create_dirs", []):
        target_dir = os.path.join(final_output_folder, folder)
        os.makedirs(target_dir, exist_ok=True)
        print(f"   📁 建立資料夾: {folder}")

    print(f"\n✅ 打包完成！輸出位置：\n   👉 {final_output_folder}")
    try: os.startfile(final_output_folder)
    except: pass

if __name__ == "__main__":
    select_target_script()
    if os.path.exists(SCRIPT_NAME):
        resource_paths = prepare_safe_assets()
        try:
            build_exe(resource_paths)
        finally:
            cleanup_temp_assets()
        post_build_setup()
    input("\nPRESS ENTER TO EXIT...")