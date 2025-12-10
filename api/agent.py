# api/agent.py
import os
import json
import base64
import tempfile
import logging
from datetime import datetime
from mimetypes import guess_type

# External libs (in requirements.txt)
import requests
import google.generativeai as genai
import fitz  # PyMuPDF
from urlextract import URLExtract

# --- Import your local training / product modules if present ---
# from training import instructions, faq_data
# import products_data

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agent")

# Configure model from environment
GEN_API = os.environ.get("GEN_API")  # Gemini API key
if not GEN_API:
    logger.warning("GEN_API env var is not set. Model calls will fail.")
else:
    genai.configure(api_key=GEN_API)

MODEL_NAME = os.environ.get("MODEL_NAME", "gemini-2.0-flash")

# small helper URL extractor (cache in /tmp)
class CustomURLExtract(URLExtract):
    def _get_cache_file_path(self):
        cache_dir = "/tmp"
        return os.path.join(cache_dir, "tlds-alpha-by-domain.txt")

extractor = CustomURLExtract(limit=1)

# Create model object helper
def make_model():
    generation_config = {
        "temperature": 0.9,
        "top_p": 0.95,
        "top_k": 0,
        "max_output_tokens": 1024,
    }
    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT","threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH","threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT","threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT","threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    ]
    return genai.GenerativeModel(
        model_name=MODEL_NAME,
        generation_config=generation_config,
        safety_settings=safety_settings
    )

# Utility: save a base64 file to temp path and return path
def save_base64_file(filename, b64content):
    suffix = os.path.splitext(filename)[1] or ""
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="upload_")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(base64.b64decode(b64content))
    return path

# Handle uploaded file: if PDF -> convert first page to image (optional)
def prepare_file_for_model(path, mime):
    """
    For PDFs, convert to an image and return that image path.
    For images or audio, return the path directly.
    """
    if mime == "application/pdf" or path.lower().endswith(".pdf"):
        try:
            doc = fitz.open(path)
            if len(doc) > 0:
                page = doc[0]
                pix = page.get_pixmap(dpi=150)
                img_path = path + ".jpg"
                pix.save(img_path)
                return img_path
        except Exception as e:
            logger.exception("PDF -> image conversion failed: %s", e)
            return path
    return path

# Main handler
def handler(request):
    """
    Vercel serverless handler signature.
    Expects: request: dict with keys 'method', 'headers', 'body', 'query' (when GET)
    Returns: dict with statusCode, headers, body
    """
    method = request.get("method", "GET").upper()

    # --- Basic CORS headers to allow browser use ---
    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "OPTIONS, GET, POST",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Content-Type": "application/json",
    }

    if method == "OPTIONS":
        return {"statusCode": 204, "headers": cors_headers, "body": ""}

    if method == "GET":
        # simple liveness / instructions
        body = {"ok": True, "time": datetime.utcnow().isoformat()}
        return {"statusCode": 200, "headers": cors_headers, "body": json.dumps(body)}

    # POST -> chat / files
    try:
        raw = request.get("body", "") or ""
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")

        payload = json.loads(raw) if raw else {}
        query = payload.get("query", "").strip()
        files = payload.get("files", [])  # list of {filename, content (base64), mime}

        model = make_model()

        uploaded_file_paths = []
        file_objs_for_model = []

        # Save files locally and prepare for model upload
        for f in files:
            fname = f.get("filename", f"file_{len(uploaded_file_paths)}")
            content_b64 = f.get("content", "")
            mime = f.get("mime", guess_type(fname)[0] or "")
            if not content_b64:
                continue
            path = save_base64_file(fname, content_b64)
            path2 = prepare_file_for_model(path, mime)
            uploaded_file_paths.append(path2)
            # Upload to the model provider (Gemini) if supported
            try:
                file_obj = genai.upload_file(path=path2, display_name=fname)
                file_objs_for_model.append(file_obj)
            except Exception as e:
                logger.warning("Could not upload file to genai: %s", e)

        # Build prompt/instruction. If you have training.instructions import use it.
        # Try to include instructions module if present
        base_instruction = ""
        try:
            from training import instructions as training_instructions
            base_instruction = getattr(training_instructions, "instructions", "")
        except Exception:
            base_instruction = ""

        # Compose the model input
        prompt_parts = []
        if base_instruction:
            prompt_parts.append(base_instruction)
        if query:
            prompt_parts.append(query)

        # If files are present, add a short note
        if file_objs_for_model:
            prompt_parts.append("Files uploaded by the user are attached for reference. Answer based on them where relevant.")

        model_input = "\n\n".join(prompt_parts) if prompt_parts else "Hello"

        # Call model.generate_content — if files were uploaded pass them as additional inputs
        response_text = ""
        try:
            if file_objs_for_model:
                # pass list: [text_prompt, file1, file2, ...] — mirrors prior usage patterns
                model_inputs = [model_input] + file_objs_for_model
                response = model.generate_content(model_inputs)
            else:
                response = model.generate_content(model_input)

            # response may have .text or ._result depending on SDK version
            if getattr(response, "text", None):
                response_text = response.text
            else:
                # fallback to result parsing
                try:
                    # SDK returns complex object in some versions
                    response_text = response._result.candidates[0].content.parts[0].text
                except Exception:
                    response_text = str(response)
        except Exception as e:
            logger.exception("Model call failed: %s", e)
            response_text = "Sorry — the AI model failed to produce a reply."

        # Clean up temp files
        for p in uploaded_file_paths:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass

        body = {"reply": response_text}
        return {"statusCode": 200, "headers": cors_headers, "body": json.dumps(body)}

    except Exception as exc:
        logger.exception("Error in agent handler: %s", exc)
        return {
            "statusCode": 500,
            "headers": cors_headers,
            "body": json.dumps({"error": "internal_server_error", "details": str(exc)})
        }
