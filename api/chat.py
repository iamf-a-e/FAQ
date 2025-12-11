from flask import Flask, request, jsonify
import google.generativeai as genai
import os

app = Flask(__name__)

genai.configure(api_key=os.environ.get("GEN_API"))

model = genai.GenerativeModel("gemini-2.5-flash")

@app.post("/")
def handler():
    try:
        data = request.get_json()
        message = data.get("message", "")

        response = model.generate_content(message)

        return jsonify({
            "success": True,
            "response": response.text
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
