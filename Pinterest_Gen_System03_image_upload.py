import os
import time
import sys
import pandas as pd
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from datetime import datetime, timedelta

# ----------------------------------------------------------------------
# Paths and Global Config
# ----------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Default roots for Excel and Images
DEFAULT_EXCEL_ROOT = os.path.join(SCRIPT_DIR, "Generated_Content")
DEFAULT_IMAGE_ROOT = os.path.join(SCRIPT_DIR, "Generated_Images")

BOARD_MAPPING_FILE = os.path.join(SCRIPT_DIR, "board_mapping.txt")
DRIVE_CONFIG_FILE = os.path.join(SCRIPT_DIR, "drive_config.txt")
CSV_UPLOAD_BASE = os.path.join(SCRIPT_DIR, "csv_to_upload")
CLIENT_SECRET_FILE = os.path.join(SCRIPT_DIR, "client_secret.json")
TOKEN_FILE = os.path.join(SCRIPT_DIR, "token.json")
SCOPES = ["https://www.googleapis.com/auth/drive"]


# ----------------------------------------------------------------------
# 1. Startup File Check (Blocking loop)
# ----------------------------------------------------------------------
def check_system_requirements():
    required_files = {
        CLIENT_SECRET_FILE: "Google API credentials (client_secret.json)",
        BOARD_MAPPING_FILE: "Pinterest board mapping file (board_mapping.txt)",
        DRIVE_CONFIG_FILE: "Google Drive folder ID config (drive_config.txt)",
    }

    while True:
        missing = []
        for path, description in required_files.items():
            if not os.path.exists(path):
                missing.append(f"MISSING: {os.path.basename(path)} ({description})")
                if path.endswith(".txt"):
                    with open(path, "w", encoding="utf-8") as f:
                        if "board_mapping" in path:
                            f.write(
                                "# Format -> Style_ID : Board Name\n1 : Sample Board"
                            )
                        else:
                            f.write("PASTE_YOUR_FOLDER_ID_HERE")

        if not missing:
            print("\n✅ System files verified.")
            break

        print("\n" + "=" * 60)
        print(" ERROR: REQUIRED CONFIGURATION FILES ARE MISSING")
        print("=" * 60)
        for msg in missing:
            print(f" ❌ {msg}")
        print("-" * 60)

        choice = (
            input("\nAction: [R]etry scanning or [E]xit program? (R/E): ")
            .strip()
            .upper()
        )
        if choice == "E":
            sys.exit(0)


# ----------------------------------------------------------------------
# Helper: Validate and Get Folder
# ----------------------------------------------------------------------
def get_valid_folder(default_path, folder_description):
    """Checks if a folder exists. If not, prompts user for a new name."""
    current_path = default_path
    while not os.path.isdir(current_path):
        print(f"\n🛑 Error: {folder_description} folder not found at: {current_path}")
        new_name = input(
            f"Please enter the correct folder name for {folder_description} (or 'exit' to quit): "
        ).strip()
        if new_name.lower() == "exit":
            sys.exit(0)
        current_path = os.path.join(SCRIPT_DIR, new_name)
    return current_path


# ----------------------------------------------------------------------
# Google Drive API Logic
# ----------------------------------------------------------------------
def get_drive_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())
    return build("drive", "v3", credentials=creds)


def upload_to_drive(service, file_path, filename, folder_id):
    for attempt in range(3):
        try:
            media = MediaFileUpload(file_path, resumable=True)
            file_metadata = {"name": filename, "parents": [folder_id]}
            print(f"📤 Uploading ({attempt+1}/3): {filename}...")
            file = (
                service.files()
                .create(body=file_metadata, media_body=media, fields="id")
                .execute()
            )
            # Ensure file is public so Pinterest can read it
            service.permissions().create(
                fileId=file["id"], body={"type": "anyone", "role": "reader"}
            ).execute()
            return f"https://drive.google.com/uc?id={file['id']}"
        except Exception as e:
            print(f"⚠ Attempt {attempt+1} failed: {e}")
            if attempt < 2:
                time.sleep(2)
    return None


# ----------------------------------------------------------------------
# 2. Main Process
# ----------------------------------------------------------------------
def main():
    check_system_requirements()

    # Step 1: Locate Excel Root
    excel_root = get_valid_folder(DEFAULT_EXCEL_ROOT, "Excel Input (Generated_Content)")

    excel_files = [
        f
        for f in os.listdir(excel_root)
        if f.endswith(".xlsx") and not f.startswith("~$")
    ]
    if not excel_files:
        print(f"\n🛑 No Excel files found in '{excel_root}'.")
        return

    print("\n--- Excel File Selection ---")
    for i, f in enumerate(excel_files):
        print(f"[{i+1}] {f}")

    try:
        choice = int(input("\nSelect file number: ")) - 1
        if choice < 0 or choice >= len(excel_files):
            raise ValueError
        selected_excel = excel_files[choice]
    except ValueError:
        print("Invalid selection.")
        return

    file_stem = os.path.splitext(selected_excel)[0]

    # Step 2: Locate Image Root
    image_root = get_valid_folder(DEFAULT_IMAGE_ROOT, "Images (Generated_Images)")

    # Optional: Prompt for a specific sub-folder inside the image root
    img_sub_folder = (
        input(f"Enter image sub-folder name (Default: {file_stem}): ").strip()
        or file_stem
    )
    image_dir = os.path.join(image_root, img_sub_folder)

    is_test = input("Enable Single Test Mode? (Y/N): ").strip().lower() == "y"

    with open(DRIVE_CONFIG_FILE, "r") as f:
        # Read first non-empty line that isn't a comment
        lines = f.read().splitlines()
        drive_id = next(
            (
                line.strip()
                for line in lines
                if line.strip() and not line.startswith("#")
            ),
            None,
        )

    if not drive_id:
        print("Error: No valid Drive ID found in drive_config.txt")
        return

    date_in = input("Start Date (YYYY-MM-DD): ").strip()
    time_in = input("Start Time (HH:MM): ").strip()
    try:
        start_dt = datetime.strptime(f"{date_in} {time_in}", "%Y-%m-%d %H:%M")
    except:
        start_dt = datetime.now()

    interval = int(input("Interval (minutes, default 30): ") or "30")

    # Step 3: Output Setup
    output_dir = os.path.join(CSV_UPLOAD_BASE, file_stem)
    os.makedirs(output_dir, exist_ok=True)

    mapping = {}
    with open(BOARD_MAPPING_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if ":" in line and not line.startswith("#"):
                p = line.split(":")
                try:
                    mapping[int(p[0].strip())] = p[1].strip()
                except:
                    pass

    # Step 4: Run API and Processing
    service = get_drive_service()
    excel_path = os.path.join(excel_root, selected_excel)

    # 載入 Excel 物件，準備讀取多個 Sheet
    xls = pd.ExcelFile(excel_path)
    final_rows, error_log = [], []

    print(f"\n🚀 Processing: {selected_excel}...")

    # [Modification 1] Loop through all sheets
    for sheet_name in xls.sheet_names:
        print(f"   📄 Reading Sheet: {sheet_name}...")
        df = pd.read_excel(excel_path, sheet_name=sheet_name).fillna("")
        df.columns = df.columns.str.strip()

        for idx, row in df.iterrows():
            img_prefix = str(
                row.get("Pin_Name_For_Upload") or row.get("Image_name")
            ).strip()
            row_errors = []

            # Fuzzy Image Search
            actual_img = None
            if os.path.exists(image_dir):
                for f in os.listdir(image_dir):
                    if f.startswith(img_prefix) and f.lower().endswith(
                        (".png", ".jpg", ".jpeg")
                    ):
                        actual_img = f
                        break

            # Fallback search by exact Image_name if prefix search fails
            if not actual_img:
                exact_name = str(row.get("Image_name", "")).strip()
                if exact_name and os.path.exists(os.path.join(image_dir, exact_name)):
                    actual_img = exact_name

            if not actual_img:
                row_errors.append(f"Image starting with '{img_prefix}' not found")

            try:
                # Handle Style ID (convert float to int string properly)
                raw_sid = row.get("Applied_Style_ID", 0)
                if isinstance(raw_sid, float):
                    sid = int(raw_sid)
                else:
                    sid = int(float(str(raw_sid)))  # Handle string '1.0'

                board = mapping.get(sid)
                if not board:
                    row_errors.append(f"Style ID {sid} missing in mapping")
            except:
                row_errors.append("Invalid Style ID")

            if row_errors:
                err_data = row.to_dict()
                err_data["Sheet"] = sheet_name  # Add sheet info to error log
                err_data["Failure_Reason"] = "; ".join(row_errors)
                error_log.append(err_data)
            else:
                img_full_path = os.path.join(image_dir, actual_img)
                url = upload_to_drive(service, img_full_path, actual_img, drive_id)
                if url:
                    # [Modification 3] Fixed CSV format (Added Thumbnail, changed Date format)
                    final_rows.append(
                        {
                            "Title": str(row.get("Pin_Title")).strip(),
                            "Media URL": url,
                            "Pinterest board": board,
                            "Thumbnail": "",  # Required by Pinterest Bulk Upload
                            "Description": str(row.get("Pin_Description")).strip(),
                            "Link": str(row.get("Affiliate_Link")).strip(),
                            "Publish date": start_dt.strftime(
                                "%Y-%m-%d %H:%M:%S"
                            ),  # Pinterest format
                            "Keywords": str(row.get("Pin_Keywords")).strip(),
                        }
                    )
                    start_dt += timedelta(minutes=interval)
                else:
                    err_data = row.to_dict()
                    err_data["Sheet"] = sheet_name
                    err_data["Failure_Reason"] = "Drive upload failed"
                    error_log.append(err_data)

            if is_test:
                print(
                    f"\n🧪 Single Test Mode: Process finished for row #1 in sheet {sheet_name}."
                )
                break

        if is_test:
            break

    # Final Exports
    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )  # [Modification 2] Generate timestamp

    if error_log:
        pd.DataFrame(error_log).to_excel(
            os.path.join(output_dir, f"{file_stem}_update_{timestamp}.xlsx"),
            index=False,
        )

    # Standard columns for Pinterest Bulk Upload
    csv_columns = [
        "Title",
        "Media URL",
        "Pinterest board",
        "Thumbnail",
        "Description",
        "Link",
        "Publish date",
        "Keywords",
    ]

    if final_rows:
        df_out = pd.DataFrame(final_rows)
        for b_name, group in df_out.groupby("Pinterest board"):
            safe_b = "".join(x for x in b_name if x.isalnum() or x in " _").replace(
                " ", "_"
            )
            # [Modification 2] Add timestamp to filename
            output_filename = f"upload_{timestamp}_{safe_b}.csv"

            # [Modification 3] Ensure correct column order
            group = group.reindex(columns=csv_columns, fill_value="")

            group.to_csv(
                os.path.join(output_dir, output_filename),
                index=False,
                encoding="utf-8-sig",
            )
            print(f"✅ Saved: {output_filename}")

    print(f"\n🎉 Finished. Check: {output_dir}")


if __name__ == "__main__":
    main()
