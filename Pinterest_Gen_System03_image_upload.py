import os
import pandas as pd
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from datetime import datetime, timedelta

# ----------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------
script_dir = os.path.dirname(os.path.abspath(__file__))
GENERATED_CONTENT_FOLDER = os.path.join(script_dir, "Generated_Content")
BOARD_MAPPING_FILE = os.path.join(script_dir, "board_mapping.txt")
DRIVE_CONFIG_FILE = os.path.join(script_dir, "drive_config.txt")

CLIENT_SECRET_FILE = os.path.join(script_dir, "client_secret.json")
TOKEN_FILE = os.path.join(script_dir, "token.json")
SCOPES = ["https://www.googleapis.com/auth/drive"]

# ----------------------------------------------------------------------
# Config Validation
# ----------------------------------------------------------------------
def ensure_drive_config_exists():
    if not os.path.isfile(DRIVE_CONFIG_FILE):
        with open(DRIVE_CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write("YOUR_GOOGLE_DRIVE_FOLDER_ID_HERE")
        print("\n⚠ Created drive_config.txt — enter Drive Folder ID before running again.\n")
        exit()

def ensure_board_mapping_example():
    if not os.path.isfile(BOARD_MAPPING_FILE):
        example = """# REQUIRED — Pinterest board mapping
# Format: Style_ID : Pinterest_Board_Name (must match exactly)

1: Cozy Living Room
2: Minimalist Home Decor
3: Natural Aesthetic
"""
        with open(BOARD_MAPPING_FILE, "w", encoding="utf-8") as f:
            f.write(example)
        print("\n⚠ Created board_mapping.txt — fill Pinterest board names and rerun.\n")
        exit()

# ----------------------------------------------------------------------
# Google Drive Auth
# ----------------------------------------------------------------------
def get_drive_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            print("\n🌐 Opening browser for Google authentication...")
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())
    return build("drive", "v3", credentials=creds)

def validate_drive_folder(service, folder_id):
    try:
        service.files().get(fileId=folder_id, fields="id").execute()
        print("📁 Drive folder verified.")
        return True
    except Exception:
        print("\n❌ ERROR: Invalid Google Drive folder ID or no access. Fix drive_config.txt and sharing.\n")
        return False

# ----------------------------------------------------------------------
# Upload File
# ----------------------------------------------------------------------
def upload_to_drive(service, file_path, filename, folder_id):
    try:
        media = MediaFileUpload(file_path, resumable=True)
        file_metadata = {"name": filename, "parents": [folder_id]}
        print(f"📤 Uploading: {filename}...")
        file = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
        service.permissions().create(fileId=file["id"], body={"type": "anyone", "role": "reader"}).execute()
        return f"https://drive.google.com/uc?id={file['id']}"
    except Exception as e:
        print(f"❌ Upload failed: {filename} — {e}")
        return None

# ----------------------------------------------------------------------
# Load Board Mapping
# ----------------------------------------------------------------------
def load_board_mapping():
    mapping = {}
    with open(BOARD_MAPPING_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(":", 1)
            if len(parts) == 2:
                try:
                    sid = int(parts[0].strip())
                    mapping[sid] = parts[1].strip()
                except Exception:
                    # skip invalid mapping lines
                    continue
    return mapping

# ----------------------------------------------------------------------
# User Inputs
# ----------------------------------------------------------------------
def get_user_inputs():
    ensure_drive_config_exists()
    ensure_board_mapping_example()

    with open(DRIVE_CONFIG_FILE, "r", encoding="utf-8") as f:
        drive_folder = f.read().strip()

    if "YOUR_" in drive_folder or not drive_folder:
        print("\n🛑 Please update drive_config.txt with your Drive folder ID.\n")
        exit()

    print("\n=== Pinterest Bulk Upload Automation ===")

    excel_files = [f for f in os.listdir(GENERATED_CONTENT_FOLDER) if f.endswith(".xlsx")]
    if not excel_files:
        print(f"\n🛑 No Excel files found in {GENERATED_CONTENT_FOLDER}")
        exit()
    print("\nExcel files found:")
    for ex in excel_files:
        print(" -", ex)

    excel_name = ""
    while excel_name not in excel_files:
        excel_name = input("\nEnter Excel file name (with .xlsx): ").strip()

    print("\n⚠ Board names MUST match Pinterest exactly (case-sensitive).")
    confirm = input("Have you verified board_mapping.txt is correct? (Y/N): ").strip().lower()
    if confirm != "y":
        print("\n🛑 STOPPED — Please correct board_mapping.txt before continuing.\n")
        exit()

    start_date = input("\nStart Date (YYYY-MM-DD): ").strip()
    start_time = input("Start Time (HH:MM): ").strip()
    try:
        start_dt = datetime.strptime(f"{start_date} {start_time}", "%Y-%m-%d %H:%M")
    except Exception:
        print("⚠ Invalid date/time format — using now.")
        start_dt = datetime.now()

    interval = int(input("\nMinutes between posts (default 30): ").strip() or "30")
    daily_limit = int(input("Daily upload limit (default 20): ").strip() or "20")
    test_mode = input("Single test mode? (Y/N): ").strip().lower() == "y"

    return drive_folder, excel_name, start_dt, interval, daily_limit, test_mode

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    drive_folder, excel_name, post_time, interval, daily_limit, test_mode = get_user_inputs()

    mapping = load_board_mapping()
    if not mapping:
        print("\n🛑 board_mapping.txt has no valid entries. Fill it and rerun.")
        return

    service = get_drive_service()
    if not validate_drive_folder(service, drive_folder):
        return

    excel_path = os.path.join(GENERATED_CONTENT_FOLDER, excel_name)
    image_dir = os.path.join(GENERATED_CONTENT_FOLDER, os.path.splitext(excel_name)[0])

    if not os.path.exists(excel_path):
        print(f"\n🛑 Excel file not found: {excel_path}")
        return
    if not os.path.isdir(image_dir):
        print(f"\n🛑 Image folder missing: {image_dir}")
        return

    try:
        xls = pd.ExcelFile(excel_path)
    except Exception as e:
        print(f"❌ Cannot open Excel file: {e}")
        return

    required_columns = ["Affiliate_Link", "Pin_Name_For_Upload", "Image_name", "Pin_Title", "Pin_Description", "Pin_Keywords", "Applied_Style_ID"]
    pinterest_rows = []
    error_rows = []

    for sheet in xls.sheet_names:
        try:
            df = pd.read_excel(excel_path, sheet_name=sheet, engine='openpyxl')
        except Exception as e:
            print(f"⚠ Skipping sheet {sheet} — read error: {e}")
            continue

        df.columns = df.columns.str.strip()

        # If sheet missing required columns, push all rows to error with message
        missing_cols = [c for c in required_columns if c not in df.columns]
        if missing_cols:
            msg = f"Missing required columns in sheet '{sheet}': {missing_cols}"
            print("❌", msg)
            for idx, r in df.iterrows():
                er = r.to_dict()
                er["Sheet_Name"] = sheet
                er["Row_Index"] = idx + 2  # +2 approximates Excel row number (header + 1)
                er["Error_Message"] = msg
                error_rows.append(er)
            continue

        for idx, r in df.iterrows():
            row_index_excel = idx + 2  # header + 1 => Excel-like index
            try:
                # Read raw values (not stringified) to properly detect NaN
                affiliate_val = r.get("Affiliate_Link")
                pin_name_val = r.get("Pin_Name_For_Upload") or r.get("Image_name")  # accept either column if present
                title_val = r.get("Pin_Title")
                desc_val = r.get("Pin_Description")
                keywords_val = r.get("Pin_Keywords")
                style_raw = r.get("Applied_Style_ID")

                row_errors = []

                # Validate presence (use pd.isna to detect NaN)
                if pd.isna(affiliate_val) or str(affiliate_val).strip() == "":
                    row_errors.append("Missing Affiliate_Link")
                if pd.isna(pin_name_val) or str(pin_name_val).strip() == "":
                    row_errors.append("Missing Pin_Name_For_Upload / Image_name")
                if pd.isna(title_val) or str(title_val).strip() == "":
                    row_errors.append("Missing Pin_Title")
                if pd.isna(desc_val) or str(desc_val).strip() == "":
                    row_errors.append("Missing Pin_Description")
                if pd.isna(keywords_val) or str(keywords_val).strip() == "":
                    row_errors.append("Missing Pin_Keywords")
                # Validate style id
                style_id = None
                if pd.isna(style_raw) or str(style_raw).strip() == "":
                    row_errors.append("Missing Applied_Style_ID")
                else:
                    # accept int or float values (like 1.0), or strings convertible to numbers
                    try:
                        # float first to handle 1.0, then int
                        style_id = int(float(style_raw))
                    except Exception:
                        row_errors.append("Invalid Applied_Style_ID format")

                # If style_id present, check mapping
                board_name = ""
                if style_id is not None:
                    if style_id in mapping:
                        board_name = mapping[style_id]
                    else:
                        row_errors.append(f"No board mapping for Style_ID {style_id}")

                # If earlier errors exist, write to error_rows and skip
                if row_errors:
                    er = r.to_dict()
                    er["Sheet_Name"] = sheet
                    er["Row_Index"] = row_index_excel
                    er["Error_Message"] = "; ".join(row_errors)
                    error_rows.append(er)
                    print(f"⚠ Row {row_index_excel} in '{sheet}' -> {er['Error_Message']}")
                    continue

                # Build image path and check file exists
                pin_name_str = str(pin_name_val).strip()
                image_filename = f"{pin_name_str}.png"
                image_path = os.path.join(image_dir, image_filename)
                if not os.path.isfile(image_path):
                    er = r.to_dict()
                    er["Sheet_Name"] = sheet
                    er["Row_Index"] = row_index_excel
                    er["Error_Message"] = f"Missing image file: {image_filename}"
                    error_rows.append(er)
                    print(f"⚠ Row {row_index_excel} in '{sheet}' -> Missing image file: {image_filename}")
                    continue

                # All validation passed — upload image
                media_url = upload_to_drive(service, image_path, image_filename, drive_folder)
                if not media_url:
                    er = r.to_dict()
                    er["Sheet_Name"] = sheet
                    er["Row_Index"] = row_index_excel
                    er["Error_Message"] = "Upload failed or returned no URL"
                    error_rows.append(er)
                    print(f"⚠ Row {row_index_excel} in '{sheet}' -> Upload failed for {image_filename}")
                    continue

                # Append to pinterest rows
                pinterest_rows.append({
                    "Title": str(title_val).strip(),
                    "Media URL": media_url,
                    "Pinterest board": board_name,
                    "Thumbnail": "",
                    "Description": str(desc_val).strip(),
                    "Link": str(affiliate_val).strip(),
                    "Publish date": post_time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "Keywords": str(keywords_val).strip()
                })

                # advance time and daily counters
                post_time += timedelta(minutes=interval)

                if test_mode:
                    break

            except Exception as ex:
                # unexpected per-row error -> add to error_rows
                er = r.to_dict()
                er["Sheet_Name"] = sheet
                er["Row_Index"] = row_index_excel
                er["Error_Message"] = f"Unhandled exception: {ex}"
                error_rows.append(er)
                print(f"❌ Row {row_index_excel} in '{sheet}' unhandled exception: {ex}")
                continue

        if test_mode:
            break

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # write error CSV if any
    if error_rows:
        df_err = pd.DataFrame(error_rows)
        err_file = f"ERROR_ROWS_{timestamp}.csv"
        err_path = os.path.join(script_dir, err_file)
        try:
            df_err.to_csv(err_path, index=False, encoding="utf-8-sig")
            print(f"\n🚨 {len(df_err)} error rows written to: {err_file}")
        except Exception as e:
            print(f"❌ Failed to write error CSV: {e}")

    # If no valid rows, stop
    if not pinterest_rows:
        print("\n🛑 No valid rows to export. Exiting.")
        return

    # group by board and export CSVs (200 rows max)
    df_out = pd.DataFrame(pinterest_rows)
    grouped = df_out.groupby("Pinterest board")

    print("\n📦 Exporting CSV files...\n")
    for board, group in grouped:
        safe_board = "".join(c for c in board if c.isalnum() or c in (" ", "_")).replace(" ", "_").strip()
        if not safe_board:
            safe_board = "NO_BOARD"
        total = len(group)
        chunks = (total + 199) // 200
        for i in range(chunks):
            chunk = group.iloc[i * 200:(i + 1) * 200]
            filename = (
                f"pinterest_bulk_upload_{timestamp}_{safe_board}.csv"
                if chunks == 1 else
                f"pinterest_bulk_upload_{timestamp}_{safe_board}_{i+1}.csv"
            )
            out_path = os.path.join(script_dir, filename)
            try:
                chunk.to_csv(out_path, index=False, encoding="utf-8-sig")
                print(f"💾 Saved {filename} ({len(chunk)} rows)")
            except Exception as e:
                print(f"❌ Failed saving {filename}: {e}")

    print("\n🎉 Process complete.")

if __name__ == "__main__":
    main()
