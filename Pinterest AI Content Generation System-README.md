# **🤖 Pinterest AI Content Generation System**

This is a comprehensive 3-stage automation system designed to generate and prepare content for the Pinterest bulk uploader using the Gemini AI and Google Drive.

This system will:

1. **Generate Content:** Create unique image prompts, titles, descriptions, and keywords based on product and style data.  
2. **Generate Images:** Use the prompts from Step 1 to automatically generate unique product images with Gemini.  
3. **Upload & Format:** Upload the generated images to Google Drive and format all data into CSV files ready for the Pinterest bulk uploader.

## **🌟 Key Features**

* **AI Content Generation:** Automatically writes titles, descriptions, image prompts, and keywords.  
* **AI Image Generation:** Creates beautiful, Pinterest-ready images based on prompts and reference product photos.  
* **Google Drive Integration:** Automatically uploads generated images to Google Drive and retrieves shareable links.  
* **Bulk CSV Export:** Generates perfectly formatted CSV files for the Pinterest bulk uploader.  
* **Dynamic Validation:** Interactively asks whether certain fields (like `Affiliate_Link`) should be mandatory.  
* **Error Handling:** Intelligently separates *input data errors* (like missing images) from *API generation errors* (like failed API calls) into separate files for easy review.  
* **Duplicate Prevention:** Automatically detects duplicate titles during generation and attempts to rewrite them to ensure content uniqueness.  
* **Template Customization:** Uses external `.txt` files to customize the AI prompts for content and images.

---

## **⚙️ Workflow & Order of Operations**

This system is designed to be run in a specific 3-step sequence. **You must run the scripts in this order.**

### **➡️ Step 1: `Pinterest_Gen_System01_content.py` (Content Generation)**

This script reads your product and style Excel files and uses the Gemini AI to generate text content for each product-style combination.

* When run, this script will interactively ask for:  
  * `test_single` mode (Y/N)  
  * `verbose_debug` output (Y/N)  
  * Whether `Affiliate_Link` is a required field (Y/N)  
* It automatically detects and attempts to regenerate duplicate titles.  
* **Inputs:** `Pinterest_Affiliate_Data.xlsx`, `Pinterest_Affiliate_Product.xlsx`, `product_image/` (original images), `image_prompt_template.txt`, `content_prompt_template.txt`.  
* **Outputs:**  
  * `Generated_Content/Generated_Content_[timestamp].xlsx`: An Excel file containing all successfully generated data. API errors are saved to a separate sheet named `Generation_Errors` within this file.  
  * `Input_Errors_[timestamp].xlsx`: (In the root folder) A separate Excel file containing any products that failed *input validation* (e.g., missing product data, image file not found).

### **➡️ Step 2: `Pinterest_Gen_System02_image.py` (Image Generation)**

This script reads the `Generated_Content...xlsx` file from Step 1\. It uses the `Image_Prompt_For_AI` column and the *original* product image to generate a new, stylized image with the Gemini AI.

* **Inputs:** `Generated_Content/Generated_Content_[timestamp].xlsx` (from Step 1), `product_image/` (original images), `image_generation_instruction.txt`.  
* **Outputs:**  
  * Generated `.png` images are saved into a new subfolder: `Generated_Content/[Excel_Name_Subfolder]/` (e.g., `Generated_Content/Generated_Content_202511151500/`).

### **➡️ Step 3: `Pinterest_Gen_System03_image_upload.py` (Upload & CSV Generation)**

This script reads the Excel file from Step 1 and the generated images from Step 2\. It uploads each generated image to Google Drive, gets a shareable link, and formats all the data into the final CSV files for Pinterest.

* **Inputs:** `Generated_Content/Generated_Content_[timestamp].xlsx` (from Step 1), `Generated_Content/[Excel_Name_Subfolder]/` (images from Step 2), `board_mapping.txt`, `drive_config.txt`, `client_secret.json`.  
* **Outputs:**  
  * `pinterest_bulk_upload_[timestamp]_[board_name].csv`: The final, ready-to-upload CSV files, split by Pinterest board.  
  * `ERROR_ROWS_[timestamp].csv`: Any rows that failed final validation (e.g., missing generated image, no board mapping).  
  * `token.json`: (Auto-generated) Stores your Google Drive authentication.

---

## **📂 Required File Structure**

/Your\_Project\_Folder  
│  
├── 📜 Pinterest\_Gen\_System01\_content.py  
├── 🎨 Pinterest\_Gen\_System02\_image.py  
├── 📤 Pinterest\_Gen\_System03\_image\_upload.py  
│  
├── 🔑 .env (Contains GEMINI\_API\_KEY)  
├── 🔑 client\_secret.json (For Google Drive API)  
│  
├── 📊 Pinterest\_Affiliate\_Data.xlsx (Input)  
├── 📦 Pinterest\_Affiliate\_Product.xlsx (Input)  
│  
├── ⚙️ board\_mapping.txt (Auto-created / Must Edit)  
├── ⚙️ drive\_config.txt (Auto-created / Must Edit)  
│  
├── 📝 content\_prompt\_template.txt (Auto-created / Can Edit)  
├── 📝 image\_generation\_instruction.txt (Auto-created / Can Edit)  
├── 📝 image\_prompt\_template.txt (Auto-created / Can Edit)  
│  
├── 🖼️ /product\_image (Input)  
│   └── original\_image\_01.jpg  
│   └── original\_image\_02.png  
│  
├── 🚀 /Generated\_Content (Output)  
│   ├── Generated\_Content\_202511151500.xlsx (From Step 1\)  
│   └── /Generated\_Content\_202511151500 (From Step 2\)  
│       └── ProductID\_StyleName.png  
│  
├── ⚠️ Input\_Errors\_...xlsx (Output from Step 1\)  
├── ⚠️ ERROR\_ROWS\_...csv (Output from Step 3\)  
├── ✅ pinterest\_bulk\_upload\_...csv (Output from Step 3\)  
└── 🔒 token.json (Auto-generated by Step 3\)

---

## **🛠️ Setup and Configuration**

### **1\. Python Environment**

Install all required libraries:

Bash  
pip install pandas google-genai openpyxl python-dotenv Pillow jinja2 google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client

### **2\. Google Gemini API Key Setup**

1. Create an API Key in the [Google AI Studio](https://aistudio.google.com/).  
2. **Enable Billing:** This is a **mandatory step** for this system.  
   * While your API key grants access, Google provides different free quotas for different models.  
   * The model used in **System 01 (Text)** may work on a basic free tier.  
   * However, the model used in **System 02 (Image Generation)** (e.g., `gemini-2.5-flash-image`) **requires billing to be enabled**. The free tier limit for this model is `0`, and you will receive a `Quota exceeded` error if billing is not active.  
3. **Free Credit:** Enabling billing allows Google to charge for usage, but it also activates your $300 free credit (if your account is new).  
4. Create a file named `.env` in the root project folder.  
5. Add your single API key to the `.env` file. This one key is used for all models in this project.  
   GEMINI\_API\_KEY=Your\_API\_Key\_Here

### **3\. Google Drive API (For Step 3\)**

You need OAuth 2.0 credentials to allow the script to upload files to your Google Drive.

1. **Enable API:** Go to the [Google Cloud Console](https://console.cloud.google.com/) and enable the "Google Drive API" for your project.  
2. **Configure OAuth Consent Screen:**  
   * Go to "APIs & Services" \> "OAuth consent screen".  
   * Select "External" and fill in the required app name, user support email, etc.  
3. **Create Credentials:**  
   * Go to "Credentials" \> "+ CREATE CREDENTIALS" \> "OAuth client ID".  
   * Select "Desktop App" as the Application type.  
   * Give it a name and click "Create".  
4. **Download JSON:**  
   * After creation, click the "DOWNLOAD JSON" button.  
   * **Rename the downloaded file to `client_secret.json`** and place it in your root project folder.  
5. **Create Google Drive Folder:**  
   * Create a folder in your Google Drive where you want the images to be uploaded.  
   * Copy the **Folder ID** from the URL (e.g., `.../folders/THIS_IS_THE_ID`).  
6. **Run & Authenticate:**  
   * The first time you run `Pinterest_Gen_System03_image_upload.py`, it will:  
     * Create `drive_config.txt` and `board_mapping.txt` if they don't exist.  
     * Open a browser window for you to log in and authorize Google Drive access.  
     * Save your credentials in `token.json` for future use.  
   * **Important:** Open the created `drive_config.txt` and paste your Google Drive Folder ID into it before running the script again.

### **4\. Input Data Files**

* **`Pinterest_Affiliate_Data.xlsx`:**  
  * `Model_Config`: Configure the Gemini model to use.  
  * `Styles_Config`: Define your `Style_ID` and `style_Name`.  
  * `Process_Config`: List which sheets from `Pinterest_Affiliate_Product.xlsx` to process.  
* **`Pinterest_Affiliate_Product.xlsx`:**  
  * Must contain sheets with names that match the entries in the `Process_Config` sheet.  
  * **Required Columns:** `Product_ID`, `Product_Name`, `Image_name`, `Product_desc`. (Note: The script will automatically rename a column named `Pinterest_Angle` to `Product_desc` if it exists).  
  * **Conditionally Required Column:** `Affiliate_Link`. When you run `Pinterest_Gen_System01_content.py`, you will be asked if this field is required. If you select 'Y', products missing this link will be sent to the `Input_Errors` file. If you select 'N', it will be treated as an optional field.  
* **`/product_image`:**  
  * Place all your *original* product images here. The filenames must match the `Image_name` column in `Pinterest_Affiliate_Product.xlsx`.

### **5\. Template & Config Files**

The scripts will automatically create these `.txt` files with default content if they are missing. You can edit them to change the AI's behavior.

* **`image_prompt_template.txt` (Step 1):** Controls how the AI generates the *image prompt* (the prompt used to create the image in Step 2).  
* **`content_prompt_template.txt` (Step 1):** Controls how the AI generates the text content.  
  * **WARNING:** Do not change the `[TITLE]`, `[DESCRIPTION]`, and `[HASHTAGS]` tags. They are required by the script to parse the AI's output.  
* **`image_generation_instruction.txt` (Step 2):** Provides general instructions (e.g., style, lighting) when the AI *generates* the actual image.  
* **`board_mapping.txt` (Step 3):**  
  * **This file MUST be edited manually.**  
  * Maps the `Style_ID` from your Excel file to the exact, case-sensitive Pinterest board name.  
  * Format: `Style_ID : Pinterest_Board_Name` (e.g., `1 : Cozy Living Room`)  
* **`drive_config.txt` (Step 3):**  
  * **This file MUST be edited manually.**  
  * Place your Google Drive Folder ID here.

