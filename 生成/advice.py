from typing import Dict, Any, List, Set
import os
import requests
import json
import urllib3
import threading

# ---------- 本地 Embedding 模型（延迟加载单例） ----------
_embed_model = None
_embed_model_lock = threading.Lock()

# 默认使用 BAAI/bge-base-zh-v1.5（768 维），与 ES 已有向量维度兼容
EMB_MODEL = os.getenv("EMB_MODEL", "BAAI/bge-base-zh-v1.5")
# 本地模型推理设备：cpu / cuda / cuda:0 等
EMB_DEVICE = os.getenv("EMB_DEVICE", "cpu")


def _get_embed_model():
    """延迟加载 SentenceTransformer 模型（线程安全单例）"""
    global _embed_model
    if _embed_model is None:
        with _embed_model_lock:
            if _embed_model is None:
                from sentence_transformers import SentenceTransformer
                print(f"[Embedding] 正在加载本地模型: {EMB_MODEL} (device={EMB_DEVICE}) ...")
                _embed_model = SentenceTransformer(EMB_MODEL, device=EMB_DEVICE)
                print(f"[Embedding] 模型加载完成")
    return _embed_model


def _embed_query_text(text: str, dimension: int) -> List[float]:
    """使用本地 sentence-transformers 模型将查询文本转为向量（交给 ES script_score 用）"""
    if not text.strip():
        return []

    model = _get_embed_model()
    # sentence-transformers encode 返回 numpy array
    embedding = model.encode(text, convert_to_numpy=True).tolist()

    if len(embedding) != dimension:
        print(f"[Embedding] 警告: 模型输出维度 {len(embedding)} != ES 向量维度 {dimension}，将截断对齐")
        if len(embedding) > dimension:
            embedding = embedding[:dimension]
        else:
            embedding = embedding + [0.0] * (dimension - len(embedding))

    return embedding


def _get_vector_dims(index_name: str) -> int:
    """从 ES 索引 mapping 中读取 vector 字段维度"""
    resp = _es_request("GET", f"/{index_name}/_mapping")
    resp.raise_for_status()
    body = resp.json()
    props = body.get(index_name, {}).get("mappings", {}).get("properties", {})
    dims = (props.get("vector") or {}).get("dims")
    if isinstance(dims, int) and dims > 0:
        return dims
    # 回退到常见的 768 维
    return 768


# ---------- ES 连接配置 ----------
TOP_K = 10
ES_RETRIEVE_SIZE = 200

WILDCARDS = {"any", "任何", "不限", "all", "*", "无要求", "__ANY__"}
MATCH_KEYS = ["age", "sex", "bmi", "disease", "symptom", "risk", "population"]

ES_URL = os.getenv("ES_URL", "https://localhost:9200").rstrip("/")
ES_USERNAME = os.getenv("ES_USERNAME", "elastic")
ES_PASSWORD = os.getenv("ES_PASSWORD", "")
ES_CA_CERTS = os.getenv("ES_CA_CERTS", "")
ES_VERIFY_CERTS = os.getenv("ES_VERIFY_CERTS", "true").lower() == "true"

# 按要求固定使用该索引
ES_INDEX = "atomic_knowledge_base_py"

if not ES_VERIFY_CERTS:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _es_verify_arg():
    if ES_VERIFY_CERTS:
        if ES_CA_CERTS and os.path.exists(ES_CA_CERTS):
            return ES_CA_CERTS
        return True
    return False


def _es_request(method: str, path: str, payload: Dict[str, Any] = None) -> requests.Response:
    url = f"{ES_URL}{path}"
    return requests.request(
        method=method,
        url=url,
        auth=(ES_USERNAME, ES_PASSWORD),
        json=payload,
        timeout=30,
        verify=_es_verify_arg(),
    )


def _normalize_es_source(src: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "match_tokens": src.get("match_tokens") or src.get("matchTokens") or [],
        "advice": src.get("advice") or "",
        "category": src.get("category") or "",
        "source_file": src.get("source_file") or src.get("sourceFile") or "",
        "page_num": src.get("page_num") if src.get("page_num") is not None else src.get("pageNum"),
    }


def _get_patient_values(patient_summary: Dict[str, Any], key: str) -> Set[str]:
    val = patient_summary.get(key)
    if val is None:
        return set()
    if isinstance(val, list):
        return {str(x).strip() for x in val if str(x).strip()}

    text = str(val).strip()
    return {text} if text else set()


def _build_key_should_tokens(key: str, patient_vals: Set[str]) -> List[str]:
    tokens = []

    for v in patient_vals:
        tokens.append(f"{key}:{v}")

    for w in WILDCARDS:
        tokens.append(f"{key}:{w}")

    seen = set()
    unique_tokens = []
    for t in tokens:
        if t not in seen:
            unique_tokens.append(t)
            seen.add(t)
    return unique_tokens


def _declared_key_query(key: str) -> Dict[str, Any]:
    return {
        "bool": {
            "should": [
                {"wildcard": {"match_tokens": f"{key}:*"}},
                {"wildcard": {"matchTokens": f"{key}:*"}},
            ],
            "minimum_should_match": 1,
        }
    }


def _build_match_filters(patient_summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    filters: List[Dict[str, Any]] = []

    for key in MATCH_KEYS:
        patient_vals = _get_patient_values(patient_summary, key)
        should_tokens = _build_key_should_tokens(key, patient_vals)
        declared_query = _declared_key_query(key)

        filters.append(
            {
                "bool": {
                    "should": [
                        {
                            "bool": {
                                "must_not": [declared_query]
                            }
                        },
                        {
                            "bool": {
                                "should": [
                                    {"terms": {"match_tokens": should_tokens}},
                                    {"terms": {"matchTokens": should_tokens}},
                                ],
                                "minimum_should_match": 1,
                            }
                        },
                    ],
                    "minimum_should_match": 1,
                }
            }
        )

    return filters


def _search_atomic_knowledge_es(patient_summary: Dict[str, Any], advice_type: str) -> List[Dict[str, Any]]:
    # 确认索引存在
    head_resp = _es_request("HEAD", f"/{ES_INDEX}")
    if head_resp.status_code != 200:
        raise RuntimeError(f"ES 索引不存在或不可访问: {ES_INDEX}")

    match_filters = _build_match_filters(patient_summary)

    # 第一阶段：ES 规则匹配，取候选集
    rule_body = {
        "size": ES_RETRIEVE_SIZE,
        "_source": ["match_tokens", "matchTokens", "advice", "category", "source_file", "sourceFile", "page_num", "pageNum", "vector"],
        "query": {
            "bool": {
                "filter": [
                    {"exists": {"field": "vector"}},
                    {"term": {"category": advice_type}},
                    *match_filters,
                ]
            }
        }
    }

    resp = _es_request("POST", f"/{ES_INDEX}/_search", rule_body)
    resp.raise_for_status()
    rule_hits = ((resp.json().get("hits") or {}).get("hits") or [])

    # 第二阶段：候选过多时，用本地模型生成查询向量，交给 ES script_score 做向量重排
    if len(rule_hits) > TOP_K:
        print(f"初步规则匹配返回 {len(rule_hits)} 条，进行 ES script_score 向量重排")
        try:
            vector_dims = _get_vector_dims(ES_INDEX)
            patient_text = json.dumps(patient_summary, ensure_ascii=False)
            query_vector = _embed_query_text(patient_text, vector_dims)
            if query_vector:
                rerank_body = {
                    "size": TOP_K,
                    "_source": ["match_tokens", "matchTokens", "advice", "category", "source_file", "sourceFile", "page_num", "pageNum"],
                    "query": {
                        "script_score": {
                            "query": {
                                "bool": {
                                    "filter": [
                                        {"exists": {"field": "vector"}},
                                        {"term": {"category": advice_type}},
                                        *match_filters,
                                    ]
                                }
                            },
                            "script": {
                                "source": "cosineSimilarity(params.qv, 'vector') + 1.0",
                                "params": {"qv": query_vector}
                            }
                        }
                    },
                }
                resp2 = _es_request("POST", f"/{ES_INDEX}/_search", rerank_body)
                resp2.raise_for_status()
                rule_hits = ((resp2.json().get("hits") or {}).get("hits") or [])
            else:
                rule_hits = rule_hits[:TOP_K]
        except Exception as e:
            print(f"向量重排失败: {e}，截断取前 {TOP_K} 条")
            rule_hits = rule_hits[:TOP_K]

    normalized: List[Dict[str, Any]] = []

    for hit in rule_hits:
        src = hit.get("_source") or {}
        item = _normalize_es_source(src)
        if item.get("advice"):
            normalized.append(item)

    return normalized


def get_advice(patient_summary: Dict[str, Any], advice_type: str) -> List[Dict[str, Any]]:
    """
    根据患者摘要信息和建议类型获取建议。
    第一阶段 ES 规则匹配 → 第二阶段 ES script_score 向量重排（本地模型生成查询向量）。
    """
    try:
        hits = _search_atomic_knowledge_es(patient_summary, advice_type)
    except Exception as e:
        print(f"ES 检索失败: {e}")
        return []

    # 为每条命中结果添加稳定序号，便于后续模型引用 [1] [2] ...
    for i, item in enumerate(hits, start=1):
        marker = f"[{i}]"
        item["ref_index"] = i
        item["ref_marker"] = marker
        advice_text = str(item.get("advice") or "").strip()
        if advice_text and not advice_text.startswith(marker):
            item["advice"] = f"{marker} {advice_text}"

    print(f"ES 规则匹配后返回 {len(hits)} 条")

    return hits
