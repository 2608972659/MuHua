from flask import Flask, jsonify, request
from main import generate_all_advice

app = Flask(__name__)

@app.route("/api/generate-advice", methods=["POST"])
def generate_advice_api():
    payload = request.get_json(silent=True) or {}
    patient_profile = payload.get("patient_profile", payload)

    if not isinstance(patient_profile, dict) or not patient_profile:
        return jsonify({"error": "请求体格式错误"}), 400

    try:
        result = generate_all_advice(patient_profile)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify(result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001, debug=False)
