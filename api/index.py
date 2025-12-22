from openai import OpenAI  # OpenAI official library
from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import logging
from datetime import datetime

# ===============================
# CONFIGURATION
# ===============================

logging.basicConfig(level=logging.INFO)

GEN_API = os.environ.get("GEN_API")  # Note: variable name changed
MODEL_NAME = "gpt-4o"  # Options: "gpt-3.5-turbo", "gpt-4", "gpt-4-turbo"

if not GEN_API:
    raise RuntimeError("GEN_API environment variable not set")

# Initialize OpenAI client
client = OpenAI(api_key=GEN_API)

# Load system instructions (STATIC, SAFE)
try:
    from .instructions import instructions as SYSTEM_PROMPT
except ImportError:
    # Fallback for testing
    SYSTEM_PROMPT = "You are a helpful AI assistant specializing in Umbrella Labs services."

# ===============================
# FLASK APP
# ===============================

app = Flask(__name__)

CORS(app, resources={
    r"/api/*": {
        "origins": ["https://iamf-a-e.github.io"]
    }
})

# ===============================
# CONVERSATION STORAGE
# (Replace with Redis in production)
# ===============================

conversations = {}

def get_conversation(session_id: str):
    """
    Returns a chat session with initial system message
    """
    if session_id not in conversations:
        # Initialize conversation history with system message
        conversations[session_id] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
    return conversations[session_id]

# ===============================
# HARD SCOPE FILTER
# ===============================

ALLOWED_KEYWORDS = [
    "umbrella",
    "umbrella labs",
    "ai",
    "chatbot",
    "software",
    "automation",
    "integration",
    "api",
    "system",
    "platform",
    "support",
    "services",
]

def is_in_scope(message: str) -> bool:
    msg = message.lower()
    return any(keyword in msg for keyword in ALLOWED_KEYWORDS)

# ===============================
# ROUTES
# ===============================

@app.route("/")
def home():
    return jsonify({
        "status": "AI Agent API is running",
        "model": MODEL_NAME,
        "provider": "OpenAI ChatGPT"
    })

@app.route("/api/chat", methods=["POST", "OPTIONS"])
def chat():
    if request.method == "OPTIONS":
        return "", 200

    try:
        data = request.json or {}
        message = data.get("message", "").strip()
        session_id = data.get("session_id", "default")

        if not message:
            return jsonify({"error": "Message is required"}), 400

        # Check if message is in scope
        if not is_in_scope(message):
            return jsonify({
                "response": "I'm sorry, but I can only answer questions related to Umbrella Labs and its services. Please ask about AI, chatbots, software, automation, integration, APIs, systems, platforms, support, or services.",
                "needs_human": False,
                "session_id": session_id,
                "status": "success"
            })

        # Get conversation history
        conversation_history = get_conversation(session_id)
        
        # Add user message to history
        conversation_history.append({"role": "user", "content": message})
        
        # Call OpenAI API
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=conversation_history,
            temperature=0.6,
            max_tokens=2048,
        )
        
        # Get assistant response
        assistant_response = response.choices[0].message.content
        
        # Add assistant response to history
        conversation_history.append({"role": "assistant", "content": assistant_response})
        
        # Limit history length to prevent token overflow
        if len(conversation_history) > 20:  # Keep last 20 messages
            # Keep system message and recent messages
            conversation_history = [conversation_history[0]] + conversation_history[-19:]
            conversations[session_id] = conversation_history
        
        # Check if human intervention is needed
        needs_human = "unable_to_solve_query" in assistant_response.lower()
        clean_answer = assistant_response.replace("unable_to_solve_query", "").strip()

        return jsonify({
            "response": clean_answer,
            "needs_human": needs_human,
            "session_id": session_id,
            "status": "success"
        })

    except Exception as e:
        logging.error(f"Chat error: {str(e)}")
        return jsonify({
            "error": f"Internal server error: {str(e)}",
            "status": "error"
        }), 500

@app.route("/api/clear", methods=["POST"])
def clear_history():
    try:
        data = request.json or {}
        session_id = data.get("session_id", "default")
        conversations.pop(session_id, None)

        return jsonify({
            "message": f"Conversation cleared for session {session_id}",
            "status": "success"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/health", methods=["GET"])
def health_check():
    try:
        # Simple health check - list available models
        models = client.models.list()
        model_ids = [model.id for model in models.data]
        
        return jsonify({
            "status": "healthy",
            "model": MODEL_NAME,
            "available_models": model_ids[:10],  # Show only first 10
            "timestamp": str(datetime.now())
        })
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e)
        }), 500

# ===============================
# LOCAL DEV ONLY
# ===============================

if __name__ == "__main__":
    app.run(debug=True, port=8000)
