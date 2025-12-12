import PyInstaller.__main__
import shutil
import os
import sys

# =======================================================
# ⚙️ 設定區域 (Configuration)
# =======================================================

# 存放 Sample 檔案的實體資料夾
SAMPLE_DIR_NAME = "sample_files"

SCRIPT_CONFIG = {
    # 🟢 1. Image Generator (Generic_Batch_Image_Generator.py)
    "image": {
        "resources": [
            ("sample", "Config_Data-sample.xlsx", "Config_Data.xlsx"),
            (
                "root",
                "image_generation_instruction.txt",
                "image_generation_instruction.txt",
            ),
            ("generate_env", None, ".env"),
        ],
        "folders": [],
        # 🔥 修正點 1: 確保建立 "Generated_Content" 資料夾
        "create_dirs": ["Generated_Images", "Logs", "ref_image", "Generated_Content"],
        # 🔥 修正點 2: 新增複製 Demo 檔案的設定
        # 格式: ("來源檔名(在sample_files內)", "目標資料夾", "目標檔名")
        "copy_files": [("Generated_Content", "Demo_Input_For_Image_Gen.xlsx")],
    },
    # 🔵 2. Content Generator (Pinterest_Gen_System01_content.py)
    "content": {
        "resources": [
            ("sample", "Config_Data-sample.xlsx", "Config_Data.xlsx"),
            (
                "sample",
                "Pinterest_Affiliate_Product-Sample.xlsx",
                "Pinterest_Affiliate_Product.xlsx",
            ),
            ("root", "image_prompt_template.txt", "image_prompt_template.txt"),
            ("root", "content_prompt_template.txt", "content_prompt_template.txt"),
            ("generate_env", None, ".env"),
        ],
        "folders": [],
        "create_dirs": ["Generated_Content", "ref_image", "Logs"],
        "copy_files": [],  # Content 模式不需要 Demo 檔
    },
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
    """準備資源：將所有需要的檔案複製到暫存區"""
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
                    print(f"   ⚠️ 警告：找不到檔案 {source_name}")
                    continue

            elif source_type == "generate_env":
                with open(destination_path, "w", encoding="utf-8") as f:
                    f.write("GEMINI_API_KEY=\n")
                print(f"   🔒 [Gen] 生成預設 .env -> 打包為 .env")

            paths_for_pyinstaller.append((destination_path, "."))

        except Exception as e:
            print(f"   ❌ 處理失敗 ({target_name}): {e}")

    return paths_for_pyinstaller


def cleanup_temp_assets():
    if os.path.exists(TEMP_BUILD_DIR):
        try:
            shutil.rmtree(TEMP_BUILD_DIR)
        except:
            pass


def select_target_script():
    global SCRIPT_NAME, EXE_NAME, CURRENT_RESOURCE_CONFIG
    files = [
        f
        for f in os.listdir(".")
        if f.endswith(".py") and f != os.path.basename(__file__)
    ]

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
                s_lower = SCRIPT_NAME.lower()

                if "content" in s_lower:
                    print(f"💡 識別模式: Content Generator")
                    CURRENT_RESOURCE_CONFIG = SCRIPT_CONFIG["content"]
                elif "image" in s_lower:
                    print(f"💡 識別模式: Image Generator")
                    CURRENT_RESOURCE_CONFIG = SCRIPT_CONFIG["image"]
                else:
                    print("⚠️ 無法識別模式，預設使用 Content 設定")
                    CURRENT_RESOURCE_CONFIG = SCRIPT_CONFIG["content"]
                break
            else:
                print("❌ 無效編號")
        except ValueError:
            print("❌ 請輸入數字")


def build_exe(resource_paths):
    print(f"\n📦 開始 PyInstaller 打包: {SCRIPT_NAME} ...")
    pyinstaller_args = [
        SCRIPT_NAME,
        f"--name={EXE_NAME}",
        "--onefile",
        "--console",
        "--clean",
        "--noconfirm",
        "--hidden-import=pandas",
        "--hidden-import=openpyxl",
        "--hidden-import=PIL",
        "--hidden-import=google.genai",
        "--hidden-import=dotenv",
        "--hidden-import=jinja2",
    ]
    separator = ";" if os.name == "nt" else ":"
    for real_path, internal_dest in resource_paths:
        add_data_arg = f"{real_path}{separator}{internal_dest}"
        pyinstaller_args.append(f"--add-data={add_data_arg}")
    PyInstaller.__main__.run(pyinstaller_args)


def post_build_setup():
    dist_dir = os.path.join("dist")
    final_output_folder = os.path.join(dist_dir, f"{EXE_NAME}_Folder")

    if os.path.exists(final_output_folder):
        shutil.rmtree(final_output_folder)
    os.makedirs(final_output_folder)

    # 1. 移動 EXE
    exe_src = os.path.join(dist_dir, f"{EXE_NAME}.exe")
    if os.path.exists(exe_src):
        shutil.move(exe_src, os.path.join(final_output_folder, f"{EXE_NAME}.exe"))

    # 2. 建立資料夾
    for folder in CURRENT_RESOURCE_CONFIG.get("create_dirs", []):
        target_dir = os.path.join(final_output_folder, folder)
        os.makedirs(target_dir, exist_ok=True)
        print(f"   📁 建立資料夾: {folder}")

    # 🔥 修正點 3: 執行複製 Demo 檔案的邏輯
    copy_files = CURRENT_RESOURCE_CONFIG.get("copy_files", [])
    if copy_files:
        print("   🎁 正在部署 Demo 檔案...")
        for src_name, target_folder, rename_to in copy_files:
            # 從 sample_files 資料夾找來源
            src_path = os.path.join(SAMPLE_DIR_NAME, src_name)

            # 目標路徑
            dest_folder_path = os.path.join(final_output_folder, target_folder)
            dest_path = os.path.join(dest_folder_path, rename_to)

            if os.path.exists(src_path):
                os.makedirs(dest_folder_path, exist_ok=True)
                shutil.copy2(src_path, dest_path)
                print(f"      ✅ 已複製 Demo: {rename_to}")
            else:
                print(f"      ⚠️ 警告: 找不到 Sample {src_path}，跳過複製。")

    print(f"\n✅ 打包完成！輸出位置：\n   👉 {final_output_folder}")
    try:
        os.startfile(final_output_folder)
    except:
        pass


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
