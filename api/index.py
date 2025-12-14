# api/index.py
import os
import logging
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import google.generativeai as genai
from . import instructions

logging.basicConfig(level=logging.INFO)

gen_api = os.environ.get("GEN_API")
model_name = "gemini-2.5-flash"
genai.configure(api_key=gen_api)

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "https://iamf-a-e.github.io"}}, supports_credentials=True)

generation_config = {
    "temperature": 0.7,
    "top_p": 0.9,
    "top_k": 40,
    "max_output_tokens": 2048,
}

safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
]

model = genai.GenerativeModel(
    model_name=model_name,
    generation_config=generation_config,
    safety_settings=safety_settings
)

conversations = {}

def get_conversation(session_id):
    if session_id not in conversations:
        conversations[session_id] = model.start_chat(history=[])
    return conversations[session_id]

@app.route('/')
def home():
    return jsonify({
        "status": "AI Agent API is running",
        "model": model_name,
        "endpoints": {
            "/api/chat": "POST - Chat with AI agent",
            "/api/clear": "POST - Clear conversation history",
            "/api/health": "GET - Health check"
        }
    })

@app.route('/api/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        message = data.get('message', '')
        session_id = data.get('session_id', 'default')
        if not message:
            return jsonify({"error": "Message is required"}), 400
        convo = get_conversation(session_id)
        if len(convo.history) == 0:
            convo.send_message(instructions.instructions)
        response = convo.send_message(message)
        answer = getattr(response, 'text', str(response))
        if "unable_to_solve_query" in answer:
            answer = answer.replace("unable_to_solve_query", "I'm having difficulty with this query.")
        return jsonify({"response": answer, "session_id": session_id, "status": "success"})
    except Exception as e:
        logging.error(f"Error in chat: {e}")
        return jsonify({"error": str(e), "status": "error"}), 500

@app.route('/api/clear', methods=['POST'])
def clear_history():
    data = request.json
    session_id = data.get('session_id', 'default')
    conversations.pop(session_id, None)
    return jsonify({"message": f"Cleared session {session_id}", "status": "success"})

@app.route('/api/health', methods=['GET'])
def health_check():
    try:
        test_model = genai.GenerativeModel(model_name)
        test_model.generate_content("Hello")
        return jsonify({"status": "healthy", "model": model_name, "gemini_connected": True, "timestamp": str(datetime.now())})
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=8000)
