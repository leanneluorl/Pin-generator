# Pinterest_Gen_System01_content.py

### Template System
This script uses two external text templates for AI generation:
- `image_prompt_template.txt`
- `content_prompt_template.txt`

These templates **do not include any variables**.  
The script automatically appends product and style information internally
after rendering the text template.

### Parsing markers
The tags `[TITLE]`, `[DESCRIPTION]`, and `[HASHTAGS]` **must not be changed**
— they are used by the parser to extract text from the model output.

### Automatic template creation
If the template files are missing, the program will create default versions
on first run. You can freely edit them to change AI tone or instructions.


💻 Python 程式碼架構：檔案處理與內容生成
前置準備
請確保您安裝了所需的函式庫，並且將您的兩個 Excel 檔案放在與 Python 腳本相同的目錄下：


Bash
pip install pandas google-genai openpyxl python-dotenv Pillow


檔案結構要求
請確保您的資料夾結構如下：

/Your_Project_Folder
├── Pinterest_Gen_System.py
├── .env (含 GEMINI_API_KEY)
├── Pinterest_Affiliate_Data.xlsx
├── product.xlsx
└── /ref_images
    └── 71EtPSbLPnL._AC_SL1500_.jpg (所有產品圖片)



自動上傳圖片至Google drive并獲得分享鏈接
===========================================================================================
🧩 一、前置條件
建立好 Google Cloud 專案
啟用「Google Drive API」
在 Google Cloud Console 建立 OAuth 憑證
您需要建立一個不同於服務帳戶的 JSON 檔案，通常稱為 client_secret.json。


設定 OAuth 同意畫面 (OAuth Consent Screen)：
在左側菜單，選擇 「API 和服務」 > 「OAuth 同意畫面」。
選擇 「外部 (External)」，然後點擊 「建立 (CREATE)」。
填寫應用程式名稱 (例如：Google Drive Uploader)、您的 Email，並儲存。這是一個必要的步驟。

建立 OAuth 用戶端 ID：
在左側菜單，選擇 「API 和服務」 > 「憑證」。
點擊頂部的 「+ 建立憑證」，然後選擇 「OAuth 用戶端 ID」。
在 「應用程式類型 (Application type)」 處，請選擇 「桌面應用程式 (Desktop App)」。
輸入名稱 (例如：Drive Desktop Client)，然後點擊 「建立」。

下載 JSON 檔案：
建立成功後，系統會顯示您的用戶端 ID 和密鑰。
點擊右側的 「下載 JSON (DOWNLOAD JSON)」 按鈕。
將下載的檔案重新命名為 client_secret.json，
將檔案放在同一個資料夾，例如：
my_project/
├── client_secret.json
├── upload.py
└── example.jpg


安裝必要套件：
pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client


