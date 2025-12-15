
import google.generativeai as genai
from flask import Flask, request, jsonify
import os 
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)

# Configuration
gen_api = os.environ.get("GEN_API")  # Gemini API Key
model_name = "gemini-2.5-flash"

# Configure Gemini
genai.configure(api_key=gen_api)

# Initialize Flask app
app = Flask(__name__)

# Configure CORS for frontend requests
from flask_cors import CORS
CORS(app, resources={
    r"/api/*": {
        "origins": [
            "https://iamf-a-e.github.io"
        ]
    }
})

# Gemini configuration
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

# Initialize the model
model = genai.GenerativeModel(
    model_name=model_name,
    generation_config=generation_config,
    safety_settings=safety_settings
)

# Global conversation storage (for demo purposes)
# In production, use a database like Redis or Vercel Postgres
conversations = {}

def get_conversation(session_id):
    """Get or create a conversation session"""
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

@app.route('/api/chat', methods=['POST', 'OPTIONS'])
def chat():
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json
        message = data.get('message', '')
        session_id = data.get('session_id', 'default')
        stream = data.get('stream', False)
        
        if not message:
            return jsonify({"error": "Message is required"}), 400
        
        # Get conversation for this session
        convo = get_conversation(session_id)
        
        # Add system prompt if first message
        if len(convo.history) == 0:
            system_prompt = """You are a helpful AI assistant. Provide clear, concise, and accurate responses. 
            If you don't know something, admit it honestly. Always maintain a professional and friendly tone."""
            convo.send_message(system_prompt)
        
        # Send message to Gemini
        response = convo.send_message(message)
        
        # Extract response text
        if hasattr(response, 'text'):
            answer = response.text
        elif hasattr(response, '_result'):
            answer = response._result.candidates[0].content.parts[0].text
        else:
            answer = str(response)
        
        # Clean response if needed
        if "unable_to_solve_query" in answer:
            answer = answer.replace("unable_to_solve_query", "I'm having difficulty with this query.")
        
        # Return response
        return jsonify({
            "response": answer,
            "session_id": session_id,
            "tokens_used": len(message.split()) + len(answer.split()),  # Approximate
            "status": "success"
        })
        
    except Exception as e:
        logging.error(f"Error in chat endpoint: {str(e)}")
        return jsonify({
            "error": str(e),
            "status": "error"
        }), 500

@app.route('/api/clear', methods=['POST'])
def clear_history():
    """Clear conversation history for a session"""
    try:
        data = request.json
        session_id = data.get('session_id', 'default')
        
        if session_id in conversations:
            del conversations[session_id]
        
        return jsonify({
            "message": f"Conversation history cleared for session {session_id}",
            "status": "success"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        # Test Gemini API connection
        test_model = genai.GenerativeModel('gemini-2.5-flash')
        test_response = test_model.generate_content("Hello")
        
        return jsonify({
            "status": "healthy",
            "model": model_name,
            "gemini_connected": True,
            "timestamp": str(datetime.now())
        })
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e)
        }), 500

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Handle file uploads (images, PDFs, etc.)"""
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400
        
        file = request.files['file']
        session_id = request.form.get('session_id', 'default')
        
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        
        # Save file temporarily (Vercel serverless has /tmp directory)
        import tempfile
        import uuid
        
        filename = f"/tmp/{uuid.uuid4()}_{file.filename}"
        file.save(filename)
        
        # Upload to Gemini
        uploaded_file = genai.upload_file(filename)
        
        # Process with Gemini
        convo = get_conversation(session_id)
        prompt = "Analyze this file and describe what you see."
        response = convo.send_message([prompt, uploaded_file])
        
        # Clean up
        os.remove(filename)
        
        return jsonify({
            "response": response.text,
            "filename": file.filename,
            "session_id": session_id,
            "status": "success"
        })
        
    except Exception as e:
        logging.error(f"Error uploading file: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500

# Vercel requires this structure
# No need for app.run() in serverless environment
if __name__ == "__main__":
    # Only run locally for testing
    app.run(debug=True, port=8000)
