# video-caption-app

## About

This repository contains a Streamlit application that creates captions for "vote in or out" social media posts. Users can upload videos, transcribe them using OpenAI, and store the captions in a Google Sheet. The app is designed for easy local development and deployment.

## Features
- Upload video files (e.g., `.mp4`, `.mov`, `.avi`) from your phone.
- Transcribe video content using the OpenAI API.
- Add transcriptions to a Google Sheet for further processing.
- Generate captions for pending rows in the sheet.
- Optional progress bar feedback during transcription.

## Prerequisites
- Python 3.7 or higher
- Git (for cloning the repository)
- Internet connection (for API calls and Streamlit)

## Installation

### Clone the Repository
```bash
git clone https://github.com/ellebythesea/video-caption-app.git
cd video-caption-app
```

### Set Up a Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
venv\Scripts\activate     # Windows
```

### Install Dependencies
Install the required Python packages:
```bash
pip install -r requirements.txt
```
Ensure `requirements.txt` includes `streamlit`, `gspread`, `oauth2client`, `python-dotenv`, `openai`, `requests`, and `pandas`.

### Configure Environment Variables
1. Create a `.env` file in the project root (do not commit this file):
   ```
   GOOGLE_SHEET_ID=your_google_sheet_id
   OPENAI_API_KEY=your_openai_api_key
   SERPER_API_KEY=your_serper_api_key
   ```
2. Obtain a Google Service Account key:
   - Create a service account in the Google Cloud Console.
   - Download the JSON key file as `credentials.json` and place it in the project root (do not commit this file).
   - Add `.env` and `credentials.json` to `.gitignore`:
     ```bash
     echo ".env" >> .gitignore
     echo "credentials.json" >> .gitignore
     git add .gitignore
     git commit -m "Update .gitignore"
     git push origin main
     ```

## Running the Application Locally
1. Activate the virtual environment (if not already active):
   ```bash
   source venv/bin/activate  # macOS/Linux
   venv\Scripts\activate     # Windows
   ```
2. Run the Streamlit app:
   ```bash
   streamlit run app.py
   ```
3. Open the browser at the provided URL (e.g., `http://localhost:8501`) and upload a video to test the transcription and Google Sheet integration.

## Troubleshooting
- **Module Not Found**: Ensure all dependencies are installed (`pip install -r requirements.txt`).
- **API Errors**: Verify `.env` contains valid API keys. Test OpenAI transcription by adding a `print` in `openai_utils.py`.
- **Google Sheets Issues**: Confirm `credentials.json` is valid and `GOOGLE_SHEET_ID` matches an existing sheet.

## Deployment to Streamlit Community Cloud
1. Link the repository to [Streamlit Community Cloud](https://share.streamlit.io):
   - Connect your GitHub account and select the `video-caption-app` repository.
2. Set the following secrets in the Streamlit app settings:
   - `GOOGLE_SHEET_ID=your_google_sheet_id`
   - `OPENAI_API_KEY=your_openai_api_key`
   - `SERPER_API_KEY=your_serper_api_key`
   - `GOOGLE_CREDENTIALS_BASE64=base64_encoded_credentials_json` (encode `credentials.json` with `base64 -w 0 credentials.json` on macOS)
3. Deploy the app. It will be available at a URL like `https://your-app-name.streamlit.app`.

## Contributing
- Fork the repository.
- Create a new branch (`git checkout -b feature-branch`).
- Make changes and commit (`git commit -m "Add new feature"`).
- Push to the branch (`git push origin feature-branch`).
- Open a pull request.

## License
This project is not explicitly licensed. Consider adding a license (e.g., MIT) if you intend to share it openly.

## Contact
For questions, open an issue on this repository or contact the maintainer.