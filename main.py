import os
import logging
import base64
import fitz                  
import google.generativeai as genai
from urlextract import URLExtract
from datetime import datetime

# If your modules exist:
from training import instructions, faq_data, products
  

# -------------------------------------------------------------------
# Logging
# -------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

# -------------------------------------------------------------------
# Environment variables
# -------------------------------------------------------------------
GEN_API = os.environ.get("GEN_API")
MODEL_NAME = os.environ.get("MODEL_NAME", "gemini-2.0-flash")

if not GEN_API:
    logger.warning("GEN_API not set — model calls will fail.")

# Configure Gemini
genai.configure(api_key=GEN_API)

# -------------------------------------------------------------------
# Model Configuration
# -------------------------------------------------------------------
generation_config = {
    "temperature": 1,
    "top_p": 0.95,
    "top_k": 0,
    "max_output_tokens": 8192,
}

safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
]

model = genai.GenerativeModel(
    model_name=MODEL_NAME,
    generation_config=generation_config,
    safety_settings=safety_settings
)

# You can keep a conversation if you like:
convo = model.start_chat(history=[])
convo.send_message(instructions.instructions)

# -------------------------------------------------------------------
# URL Extractor (cached in /tmp)
# -------------------------------------------------------------------
class CustomURLExtract(URLExtract):
    def _get_cache_file_path(self):
        return os.path.join("/tmp", "tlds-alpha-by-domain.txt")

extractor = CustomURLExtract(limit=1)

# -------------------------------------------------------------------
# PDF / IMAGE / FILE HANDLING HELPERS
# -------------------------------------------------------------------

def convert_pdf_first_page_to_image(pdf_path):
    """Convert PDF first page to JPEG for Gemini vision."""
    try:
        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            return None
        page = doc[0]
        pix = page.get_pixmap(dpi=150)
        img_path = pdf_path + ".jpg"
        pix.save(img_path)
        return img_path
    except Exception as e:
        logger.error(f"PDF conversion error: {e}")
        return None

def upload_to_gemini(path, display_name=None):
    """Upload any image/audio document to Gemini."""
    try:
        f = genai.upload_file(path=path, display_name=display_name or os.path.basename(path))
        return f
    except Exception as e:
        logger.error(f"Gemini upload error: {e}")
        return None

# -------------------------------------------------------------------
# CORE FUNCTIONS USED BY `api/agent.py`
# -------------------------------------------------------------------

def run_text_only(query: str) -> str:
    """
    Send a text-only query to the model using the conversation.
    Returns model's text response.
    """
    convo.send_message(query)
    return convo.last.text


def run_with_files(prompt: str, file_paths: list) -> str:
    """
    Handles LLM reasoning over multiple uploaded files.
    Each file path is either:
    - an image
    - a converted PDF-to-image
    - an audio file
    """
    # Upload all files to Gemini as vision/audio files
    file_objs = []
    for path in file_paths:
        obj = upload_to_gemini(path)
        if obj:
            file_objs.append(obj)

    # Build the model input
    model_inputs = [prompt] + file_objs if file_objs else [prompt]

    # Call model
    try:
        response = model.generate_content(model_inputs)
        if hasattr(response, "text"):
            return response.text
        return response._result.candidates[0].content.parts[0].text
    except Exception as e:
        logger.error(f"Model error with files: {e}")
        return "Sorry — I couldn't process your files."

def process_pdf(path):
    """
    Returns image path extracted from the first page of a PDF.
    """
    img_path = convert_pdf_first_page_to_image(path)
    return img_path or path

# -------------------------------------------------------------------
# HIGH-LEVEL UNIFIED ENTRY used by api/agent.py
# -------------------------------------------------------------------

def generate_reply(query: str, local_files: list) -> str:
    """
    This function is called by api/agent.py.
    - query: user text
    - local_files: list of local file paths saved temporarily

    Handles:
      - PDFs (convert to image)
      - Images
      - Audio
      - Multi-file reasoning
      - Plain text chats
    """

    # 1. Build base prompt with instructions
    instruction_text = instructions.instructions if hasattr(instructions, "instructions") else ""
    full_prompt = f"{instruction_text}\n\nUser query:\n{query}".strip()

    # 2. If no files → standard text conversation
    if not local_files:
        return run_text_only(full_prompt)

    # 3. For files → convert PDF then run multi-file reasoning
    processed_paths = []
    for path in local_files:
        if path.lower().endswith(".pdf"):
            img = process_pdf(path)
            processed_paths.append(img)
        else:
            processed_paths.append(path)

    return run_with_files(full_prompt, processed_paths)
