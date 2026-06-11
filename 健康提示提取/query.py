import requests
def query(system_prompt, content):
    """
    Query the API with the given content.
    """
    # ==== 1. 你的 API 地址 ====
    BASE_URL = "https://api.deepseek.com/v1/chat/completions"
    # TODO
    # ==== 2. 你的 API KEY ====
    API_KEY = ""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }

    data = {
        "model": "deepseek-chat",
        "messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content},
    ],
    }

    response = requests.post(BASE_URL, headers=headers, json=data)
    return response.json()["choices"][0]["message"]["content"]


