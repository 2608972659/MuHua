import re
import json
from pathlib import Path

from advice import get_advice
from gpu_tools import parallel_generate_advice_with_timing
from summary_tool import summarize_profile


# -------------------------------------------------------
# 解析 advice JSON 的函数
# -------------------------------------------------------
def extract_advice_list(advice_str):
    """
    输入模型返回的字符串（带```json ...```），输出纯文本 advice 列表。
    """
    if not advice_str:
        return []

    # 去掉前后代码块包裹（```json / ```text / ```）
    clean = re.sub(r"^\s*```[a-zA-Z0-9_-]*\s*", "", advice_str.strip())
    clean = re.sub(r"\s*```\s*$", "", clean).strip()

    def normalize_items(data):
        results = []
        if isinstance(data, dict):
            for v in data.values():
                if isinstance(v, list):
                    results.extend([str(x).strip() for x in v if str(x).strip()])
                elif v is not None and str(v).strip():
                    results.append(str(v).strip())
            return results
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
        if data is not None and str(data).strip():
            return [str(data).strip()]
        return []

    # 1) 标准 JSON
    try:
        data = json.loads(clean)
        results = normalize_items(data)
        if results:
            return results
    except Exception:
        pass

    # 2) 文本中夹带 JSON（提取最外层 {...}）
    left = clean.find("{")
    right = clean.rfind("}")
    if left != -1 and right != -1 and right > left:
        try:
            data = json.loads(clean[left:right + 1])
            results = normalize_items(data)
            if results:
                return results
        except Exception:
            pass

    # 3) advice1: ... / advice2: ... 这种键值文本
    kv_matches = re.findall(
        r"(?:^|\n)\s*advice\d+\s*[:：]\s*(.*?)(?=\n\s*advice\d+\s*[:：]|\Z)",
        clean,
        flags=re.IGNORECASE | re.DOTALL,
    )
    kv_results = [x.strip().strip('"').strip() for x in kv_matches if x.strip()]
    if kv_results:
        return kv_results

    # 4) - ... / • ... 这种列表文本
    line_results = []
    for raw_line in clean.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[-*•]\s+", "", line)
        if line and line not in ["[", "]", "{", "}"]:
            line_results.append(line)
    if line_results:
        return line_results

    return ["解析失败"]


# -------------------------------------------------------
# 核心 API 调用函数（给 Flask 用）
# -------------------------------------------------------
def generate_all_advice(patient_profile: dict):
    """输入 patient_profile，返回 summary + 纯文本 advice + 参考来源。"""
    summary_info = summarize_profile(patient_profile)

    # 先获取 advice_cache（ES 检索只做一次，后续生成复用同一份结果）
    advice_cache = {
        "健康生活方式": get_advice(summary_info, "健康生活方式"),
        "治疗与康复": get_advice(summary_info, "治疗与康复"),
        "急症处理": get_advice(summary_info, "急症处理"),
    }

    lifestyle_raw, treatment_raw, emergence_raw, elapsed_time = \
        parallel_generate_advice_with_timing(patient_profile, summary_info, advice_cache)

    # refs 输出用英文 key，与 API 返回格式一致
    refs = {
        "lifestyle": advice_cache["健康生活方式"],
        "treatment": advice_cache["治疗与康复"],
        "emergence": advice_cache["急症处理"],
    }

    return {
        "summary_info": summary_info,
        "lifestyle": extract_advice_list(lifestyle_raw),
        "treatment": extract_advice_list(treatment_raw),
        "emergence": extract_advice_list(emergence_raw),
        "elapsed_time": elapsed_time,
        "refs": refs,
    }


# -------------------------------------------------------
# 本地测试用
# -------------------------------------------------------
def main():
    script_dir = Path(__file__).resolve().parent
    patient_json = script_dir / "1803662573942407170.json"
    if not patient_json.exists():
        patient_json = Path("1803662573942407170.json")
    if not patient_json.exists():
        raise FileNotFoundError(f"未找到测试数据文件: {script_dir / '1803662573942407170.json'}")

    with open(patient_json, "r", encoding="utf-8") as f:
        patient_profile = json.load(f)

    result = generate_all_advice(patient_profile)

    print("\n===== Summary =====")
    print(result["summary_info"])

    print("\n===== Lifestyle Advice =====")
    for item in result["lifestyle"]:
        print("-", item)

    print("\n===== Treatment Advice =====")
    for item in result["treatment"]:
        print("-", item)

    print("\n===== Emergence Advice =====")
    for item in result["emergence"]:
        print("-", item)

    print("\nElapsed Time:", result["elapsed_time"])


if __name__ == "__main__":
    main()
