from openai import OpenAI
def query(openai_api_key, api_url, model, prompt) -> str:
    client = OpenAI(
        api_key=openai_api_key,
        base_url=api_url,
    )
    chat_response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "你是一个健康教育处方生成助手，你需要根据用户提供的患者概况和数据库中的相关知识，生成个性化的健康教育处方。"},
            {"role": "user", "content": normalize_content(prompt)},
        ],
        temperature=0.3,
        max_tokens=2000,
        top_p=0.9
    )
    return chat_response.choices[0].message.content

def normalize_content(content):
    """
    将 content 规范化为字符串：
    - 如果 content 是 list[str] → join 成一个长字符串
    - 如果 content 是 dict/list（多模态格式）→ 保持原样
    - 如果 content 是 str → 返回原样
    """
    if isinstance(content, list):
        # 如果是 ["aaaa", "bbbb"] 这种 → 合成文本
        if all(isinstance(c, str) for c in content):
            return "\n".join(content)
        else:
            # 如果是 [{"type": "text", "text": "..."}] 这种 → 多模态，直接返回
            return content
    elif isinstance(content, str):
        return content
    else:
        return content
