import requests
import json
import os

url = "http://localhost:8001/api/generate-advice"

# 读取指定的 JSON 文件作为患者档案
json_path = os.path.join(os.path.dirname(__file__), "1803662573942407170.json")
with open(json_path, "r", encoding="utf-8") as f:
    patient_data = json.load(f)

payload = {
    "patient_profile": patient_data
}

response = requests.post(
    url, 
    headers={"Content-Type": "application/json"},
    json=payload
)

print(json.dumps(response.json(), indent=2, ensure_ascii=False))