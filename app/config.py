import os
from dotenv import load_dotenv
from google import genai
from sendgrid import SendGridAPIClient

load_dotenv()

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize Gemini + SendGrid
client_gemini = genai.Client(api_key=GEMINI_API_KEY)
sendgrid_client = SendGridAPIClient(SENDGRID_API_KEY)
