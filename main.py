import google.generativeai as genai
from flask import Flask, request, jsonify
from flask_cors import CORS  # Import CORS
import os 
import logging
from datetime import datetime, timedelta
from training import instructions, faq_data

logging.basicConfig(level=logging.INFO)

# Configuration
gen_api = os.environ.get("GEN_API")  # Gemini API Key
model_name = "gemini-2.5-flash"
name = "Fae"
bot_name = "May"

app = Flask(__name__)

# Enable CORS for all domains on all routes
CORS(app)

# Or configure CORS with specific options:
# CORS(app, resources={r"/api/*": {"origins": ["http://localhost:3000", "https://yourdomain.com"]}})
# CORS(app, supports_credentials=True)  # If you need cookies/authentication

# Configure Gemini API
genai.configure(api_key=gen_api)

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
    model_name=model_name,
    generation_config=generation_config,
    safety_settings=safety_settings
)

# Initialize conversation with instructions
convo = model.start_chat(history=[])
convo.send_message(instructions.instructions)


def process_message(message_text, user_id=None, file_content=None, file_type=None):
    """
    Process user message and generate response.
    
    Args:
        message_text: Text input from user
        user_id: Optional user identifier for chat history
        file_content: Optional file content for processing
        file_type: Type of file ('image', 'pdf', 'audio')
    
    Returns:
        dict: Response containing AI reply and metadata
    """
    try:
        if file_content and file_type:
            # Handle file processing
            if file_type == 'pdf':
                # Process PDF content
                response = model.generate_content(["Read this document carefully and explain it in detail", file_content])
                ai_response = response._result.candidates[0].content.parts[0].text
                # Send to conversation with context
                convo.send_message(
                    f'''This message is based on a document sent by the user. 
                    Reply to the user assuming you read that document: {ai_response}'''
                )
            elif file_type == 'image':
                # Process image content
                response = model.generate_content(["What is in this image?", file_content])
                ai_response = response.text
                convo.send_message(
                    f'''User has sent an image. Here is the AI's analysis of the image: {ai_response}'''
                )
            elif file_type == 'audio':
                # Process audio content
                response = model.generate_content(["What is the content of this audio file?", file_content])
                ai_response = response.text
                convo.send_message(
                    f'''This message is based on audio sent by the user.
                    Reply to the user assuming you heard that audio: {ai_response}'''
                )
        else:
            # Handle text message
            convo.send_message(message_text)
        
        # Get the AI's response
        reply = convo.last.text
        
        # Check for special conditions
        if "unable_to_solve_query" in reply:
            # Log the issue if needed
            logging.info(f"User {user_id} query was not fully satisfied")
            reply = reply.replace("unable_to_solve_query", '\n')
        
        return {
            "success": True,
            "response": reply,
            "timestamp": datetime.utcnow().isoformat(),
            "model": model_name,
            "user_id": user_id
        }
        
    except Exception as e:
        logging.error(f"Error processing message: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


@app.route("/", methods=["GET"])
def index():
    """Health check endpoint"""
    return jsonify({
        "status": "online",
        "service": "AI Chat API",
        "model": model_name,
        "timestamp": datetime.utcnow().isoformat()
    })


@app.route("/api/chat", methods=["POST", "OPTIONS"])
def chat_endpoint():
    """
    Main chat endpoint for processing messages.
    
    Expected JSON payload:
    {
        "message": "User message text",
        "user_id": "optional_user_identifier",
        "file": {
            "content": "base64_encoded_file_content",
            "type": "pdf|image|audio"
        }
    }
    """
    # Handle preflight requests
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200
    
    try:
        data = request.get_json()
        
        if not data or "message" not in data:
            return jsonify({
                "success": False,
                "error": "Missing 'message' field in request"
            }), 400
        
        message_text = data["message"]
        user_id = data.get("user_id")
        file_data = data.get("file")
        
        # Process file if provided
        file_content = None
        file_type = None
        
        if file_data:
            # Note: In production, you would need to decode base64 content
            # and create appropriate file objects for the Gemini API
            file_content = file_data.get("content")
            file_type = file_data.get("type")
            
            if not file_content or not file_type:
                return jsonify({
                    "success": False,
                    "error": "File content and type are required when providing a file"
                }), 400
        
        # Process the message
        result = process_message(message_text, user_id, file_content, file_type)
        
        return jsonify(result), 200 if result["success"] else 500
        
    except Exception as e:
        logging.error(f"Error in chat endpoint: {e}")
        return jsonify({
            "success": False,
            "error": "Internal server error",
            "timestamp": datetime.utcnow().isoformat()
        }), 500


@app.route("/api/conversation/history", methods=["GET", "OPTIONS"])
def get_conversation_history():
    """Get the current conversation history"""
    # Handle preflight requests
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200
    
    try:
        history = []
        
        # Extract conversation history from Gemini's chat object
        # Note: The actual implementation may vary based on Gemini API version
        for message in convo.history:
            history.append({
                "role": message.role if hasattr(message, 'role') else "unknown",
                "content": message.text if hasattr(message, 'text') else str(message),
                "timestamp": datetime.utcnow().isoformat()  # Gemini doesn't store timestamps
            })
        
        return jsonify({
            "success": True,
            "history": history,
            "total_messages": len(history),
            "timestamp": datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logging.error(f"Error getting conversation history: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }), 500


@app.route("/api/conversation/reset", methods=["POST", "OPTIONS"])
def reset_conversation():
    """Reset the conversation history"""
    # Handle preflight requests
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200
    
    try:
        global convo
        convo = model.start_chat(history=[])
        convo.send_message(instructions.instructions)
        
        return jsonify({
            "success": True,
            "message": "Conversation reset successfully",
            "timestamp": datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logging.error(f"Error resetting conversation: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }), 500


@app.route("/api/health", methods=["GET", "OPTIONS"])
def health_check():
    """Comprehensive health check endpoint"""
    # Handle preflight requests
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200
    
    try:
        # Test model connectivity
        test_response = model.generate_content("Hello")
        
        return jsonify({
            "status": "healthy",
            "service": "AI Chat API",
            "model": model_name,
            "model_status": "connected",
            "timestamp": datetime.utcnow().isoformat(),
            "uptime": "N/A",  # You could add uptime tracking
            "version": "1.0.0"
        })
        
    except Exception as e:
        logging.error(f"Health check failed: {e}")
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }), 500


# Optional: Add custom CORS headers middleware for more control
@app.after_request
def after_request(response):
    """
    Add custom headers for CORS and security
    """
    # You can customize these headers based on your needs
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    response.headers.add('Access-Control-Allow-Credentials', 'true')  # If you need cookies
    response.headers.add('X-Content-Type-Options', 'nosniff')
    response.headers.add('X-Frame-Options', 'DENY')
    return response


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    debug = os.environ.get("DEBUG", "False").lower() == "true"
    
    # Install required packages if not already installed
    # pip install flask-cors
    
    app.run(
        host="0.0.0.0",
        port=port,
        debug=debug
    )
