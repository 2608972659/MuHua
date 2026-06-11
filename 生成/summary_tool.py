import re
from typing import Dict, Any, List

def summarize_profile(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    只抽取后续关键词匹配所需的字段，并输出标准化 match_tokens。
    不做诊疗信息抽取、不做生成。
    """

    def safe_get(d, *keys, default=None):
        cur = d
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    # -----------------------------
    # 1) age -> 小孩/成人/老年人
    # -----------------------------
    age_raw = safe_get(record, "患者信息", "年龄", default="")
    age_num = None
    if isinstance(age_raw, str):
        m = re.search(r"(\d+)", age_raw)
        if m:
            age_num = int(m.group(1))
    elif isinstance(age_raw, (int, float)):
        age_num = int(age_raw)

    age_cat = None
    if age_num is not None:
        if age_num < 18:
            age_cat = "小孩"
        elif age_num < 60:
            age_cat = "成人"
        else:
            age_cat = "老年人"

    # -----------------------------
    # 2) sex -> 男/女/任何
    # -----------------------------
    sex_raw = safe_get(record, "患者信息", "性别", default="")
    sex_cat = None
    if isinstance(sex_raw, str):
        if "男" in sex_raw:
            sex_cat = "男"
        elif "女" in sex_raw:
            sex_cat = "女"
        else:
            sex_cat = "任何"
    else:
        sex_cat = "任何"

    # -----------------------------
    # 3) bmi -> 体重过低/正常/超重/肥胖（若缺失则 None）
    # -----------------------------
    height_raw = safe_get(record, "病历内容", "体格检查", "身高", default=None)
    weight_raw = safe_get(record, "病历内容", "体格检查", "体重", default=None)

    def parse_number(x):
        if isinstance(x, str):
            m = re.search(r"(\d+(\.\d+)?)", x)
            return float(m.group(1)) if m else None
        if isinstance(x, (int, float)):
            return float(x)
        return None

    height_cm = parse_number(height_raw)
    weight_kg = parse_number(weight_raw)

    bmi_cat = None
    if height_cm and weight_kg and height_cm > 0:
        height_m = height_cm / 100.0
        bmi = weight_kg / (height_m ** 2)
        # 这里用常用 BMI 分段（你可随时改）
        if bmi < 18.5:
            bmi_cat = "体重过低"
        elif bmi < 24:
            bmi_cat = "正常"
        elif bmi < 28:
            bmi_cat = "超重"
        else:
            bmi_cat = "肥胖"

    # -----------------------------
    # 4) disease -> 固定集合内映射
    # -----------------------------
    disease_fixed = {
        "高血压": "高血压",
        "糖尿病": "糖尿病",
        "脑血管": "脑血管病",
        "慢阻肺": "慢阻肺",
        "支气管炎": "支气管炎",
        "哮喘": "哮喘",
        "肥胖症": "肥胖症",
        "肺结核": "肺结核",
        "乙肝": "乙肝",
        "感冒": "感冒",
        "肺癌": "肺癌",
        "食管癌": "食管癌",
        "胃癌": "胃癌",
        "乳腺癌": "乳腺癌",
        "宫颈癌": "宫颈癌",
        "结直肠癌": "结直肠癌",
    }

    # 收集可能的疾病来源
    past_history = safe_get(record, "病历内容", "既往史", default="")
    western_diag = safe_get(record, "诊断信息", "西医诊断", default="")
    complaint = safe_get(record, "病历内容", "主诉", default="")
    hpi = safe_get(record, "病历内容", "现病史", default="")

    disease_text = " ".join([str(past_history), str(western_diag), str(complaint), str(hpi)])

    diseases: List[str] = []
    for k, v in disease_fixed.items():
        if k in disease_text:
            diseases.append(v)

    # 如果检测不到固定疾病，但文本里有其他疾病词（如冠心病/高脂血症/胃炎），归为“其他病症”
    # 这里做个粗粒度触发：只要出现“病/症/癌/炎/梗死/支架/冠脉/心肌梗死”等医学信号就认为有其他病
    other_signal = bool(re.search(r"(病|症|癌|炎|梗死|支架|冠脉|心肌梗死|粥样硬化)", disease_text))
    if other_signal and not diseases:
        diseases.append("其他病症")
    elif other_signal and diseases:
        # 已有固定疾病时，如果还出现明显非集合疾病，可选择补一个“其他病症”
        # 你不想要的话删掉这两行就行
        non_fixed = bool(re.search(r"(冠心病|冠状动脉|心肌梗死|高脂血症|胃炎)", disease_text))
        if non_fixed and "其他病症" not in diseases:
            diseases.append("其他病症")

    if not diseases:
        diseases = ["无特定疾病"]

    # -----------------------------
    # 5) symptom -> 中文、简短，可扩展
    # -----------------------------
    symptom_vocab = [
        "发热", "咳嗽", "疼痛", "失眠", "疲劳",
        "胸痛", "便血", "头痛", "腹痛", "气短", "乏力"
    ]
    symptoms: List[str] = []
    symptom_text = " ".join([str(complaint), str(hpi)])
    for s in symptom_vocab:
        if s in symptom_text:
            symptoms.append(s)

    # -----------------------------
    # 6) risk -> 病历里没写就空
    # -----------------------------
    risk_vocab = ["吸烟", "饮酒", "缺乏运动", "高盐饮食", "睡眠不足"]
    risks: List[str] = []
    for r in risk_vocab:
        if r in disease_text:
            risks.append(r)

    # -----------------------------
    # 7) population -> 只做你要求的特定人群判定
    #    这里用“老年人/孕妇/产后/学生/工人”的简单规则
    # -----------------------------
    populations: List[str] = []
    pop_vocab = ["孕妇", "产后", "学生", "工人"]
    for p in pop_vocab:
        if p in disease_text:
            populations.append(p)
    if age_cat == "老年人":
        populations.append("老年人")

    # 去重
    diseases = sorted(set(diseases))
    symptoms = sorted(set(symptoms))
    risks = sorted(set(risks))
    populations = sorted(set(populations))

    # -----------------------------
    # 8) 组装 match_tokens
    # -----------------------------
    match_tokens: List[str] = []
    if age_cat:
        match_tokens.append(f"age:{age_cat}")
    if sex_cat:
        match_tokens.append(f"sex:{sex_cat}")
    if bmi_cat:
        match_tokens.append(f"bmi:{bmi_cat}")

    for d in diseases:
        match_tokens.append(f"disease:{d}")
    for s in symptoms:
        match_tokens.append(f"symptom:{s}")
    for r in risks:
        match_tokens.append(f"risk:{r}")
    for p in populations:
        match_tokens.append(f"population:{p}")

    return {
        "age": age_cat,
        "sex": sex_cat,
        "bmi": bmi_cat,
        "disease": diseases,
        "symptom": symptoms,
        "risk": risks,
        "population": populations
    }
