import os
from dotenv import load_dotenv

load_dotenv()

#   OpenRouter     
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

# Change this to any free OpenRouter model you prefer:
# Options:
#   "openai/gpt-4o-mini"
#   "mistralai/mistral-7b-instruct:free"
#   "google/gemma-3-27b-it:free"
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")

#   Apify 
APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")

# PRIMARY: Shiply.com marketplace scraper — real freight quotes
# https://apify.com/parseforge/shiply-com-freight-marketplace-scraper
SHIPLY_ACTOR_ID = os.getenv(
    "SHIPLY_ACTOR_ID",
    "parseforge/shiply-com-freight-marketplace-scraper",
)

# LEGACY: ShippingRates MCP actor (kept for reference)
APIFY_FREIGHT_ACTOR = os.getenv("APIFY_FREIGHT_ACTOR", "vinaybhosle/shippingrates-mcp")

# ── Google (optional — only needed if using GDrive/Gmail) ────
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GDRIVE_FOLDER_ID        = os.getenv("GDRIVE_FOLDER_ID", "")       # paste your GDrive folder ID here
GDRIVE_RECURSIVE        = os.getenv("GDRIVE_RECURSIVE", "true").lower() == "true"

# Gmail search query — see Gmail search operators:
# https://support.google.com/mail/answer/7190
GMAIL_SEARCH_QUERY = os.getenv(
    "GMAIL_SEARCH_QUERY",
    "subject:(invoice OR freight OR shipping OR bill of lading) has:attachment",
)
GMAIL_MAX_RESULTS  = int(os.getenv("GMAIL_MAX_RESULTS", "30"))

#Database
DB_PATH = os.getenv("DB_PATH", "data/cwt_shipments.db")

#Paths
SAMPLE_PDF_DIR = "data/sample_invoices"
OUTPUT_DIR     = "outputs"
PROMPT_MEMORY  = "core/prompt_memory.json"

#Anomaly threshold (%)
# If your cost is X% above market rate → flag as anomaly
ANOMALY_THRESHOLD_PCT = 20
