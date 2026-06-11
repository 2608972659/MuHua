"""
将知识库 JSONL 文件批量导入 Elasticsearch

使用方法：
1. 安装依赖：pip install elasticsearch
2. 配置 ES 连接信息（见下方 ES_CONFIG）
3. 运行：python load_to_es.py
"""

import os
import json
from typing import List, Dict
import requests
from elasticsearch import Elasticsearch, helpers

# ========== 配置区 ==========

ES_CONFIG = {
    "hosts": ["https://localhost:9200"],  # ES 地址，多个节点用列表
    "basic_auth": ("elastic", "jVaWERJ2oLooSJbdje1M"),  # 如果需要认证，取消注释
    "ca_certs": "E:\\elasticsearch-8.10.0\\config\\certs\\http_ca.crt",  # 如果使用 HTTPS，指定证书路径
}

INDEX_NAME = "health_knowledge"  # ES 索引名称
# TODO
EMBEDDING_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
EMBEDDING_API_KEY = ""
EMBEDDING_MODEL = "text-embedding-v4"
EMBEDDING_DIMENSION = 768
EMBEDDING_BATCH_SIZE = 16


INDEX_NAME = "atomic_knowledge_base_py"

KNOWLEDGE_DIR = "知识库"  # JSONL 文件所在目录

BATCH_SIZE = 500  # 批量写入大小

# ========== 索引映射（可选，首次创建索引时使用） ==========

INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "match_tokens": {
                "type": "keyword"  # 精确匹配的标签
            },
            "advice": {
                "type": "text",
                "analyzer": "ik_max_word",  # 使用 IK 中文分词器（需要安装 IK 插件）
                "search_analyzer": "ik_smart"
            },
            "category": {
                "type": "keyword"
            },
            "source_file": {
                "type": "keyword"  # 来源文件名
            },
            "page_num": {
                "type": "integer"  # 页码或位置信息
            },
            "vector": {
                "type": "dense_vector",
                "dims": EMBEDDING_DIMENSION,
                "index": True,
                "similarity": "cosine"
            },
            "model_version": {
                "type": "keyword"
            }
        }
    },
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 1
    }
}

# ========== 核心工具函数 ==========

ES_CLIENT = None  # 全局 ES 客户端实例


def connect_es() -> Elasticsearch:
    """连接到 Elasticsearch"""
    print(f"正在连接 ES: {ES_CONFIG['hosts'][0]}...")
    errors = []

    # 方案1：严格校验证书
    strict_config = dict(ES_CONFIG)
    try:
        es = Elasticsearch(**strict_config)
        if es.ping():
            info = es.info()
            print(f"✓ 已连接到 ES 集群: {info['cluster_name']} (版本 {info['version']['number']})")
            return es
        errors.append("严格证书模式 ping 失败")
    except Exception as e:
        errors.append(f"严格证书模式异常: {e}")

    # 方案2：仅在本地开发环境降级为不校验证书（解决 localhost 证书主机名不匹配）
    insecure_config = dict(ES_CONFIG)
    insecure_config.pop("ca_certs", None)
    insecure_config["verify_certs"] = False
    insecure_config["ssl_show_warn"] = False
    try:
        es = Elasticsearch(**insecure_config)
        if es.ping():
            info = es.info()
            print("! 警告: 当前使用 verify_certs=False 连接 ES（仅建议本地开发使用）")
            print(f"✓ 已连接到 ES 集群: {info['cluster_name']} (版本 {info['version']['number']})")
            return es
        errors.append("非严格证书模式 ping 失败")
    except Exception as e:
        errors.append(f"非严格证书模式异常: {e}")

    raise RuntimeError(
        "无法连接到 Elasticsearch。可能原因: 服务未启动 / 用户名密码错误 / TLS 证书主机名不匹配。"
        + " 详细信息: "
        + " | ".join(errors)
    )


def create_index_if_not_exists(es: Elasticsearch, index_name: str):
    """如果索引不存在，则创建"""
    if es.indices.exists(index=index_name):
        print(f"索引 '{index_name}' 已存在")
        return
    
    print(f"创建索引 '{index_name}'...")
    es.indices.create(index=index_name, body=INDEX_MAPPING)
    print(f"✓ 索引 '{index_name}' 创建成功")


def init_es():
    """初始化全局 ES 连接（单例模式）"""
    global ES_CLIENT
    if ES_CLIENT is None:
        ES_CLIENT = connect_es()
        create_index_if_not_exists(ES_CLIENT, INDEX_NAME)
    return ES_CLIENT


def _embed_texts(texts: List[str]) -> List[List[float]]:
    """调用与 Java 相同的向量接口生成 embeddings。"""
    if not texts:
        return []

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {EMBEDDING_API_KEY}",
    }

    vectors: List[List[float]] = []
    for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[start:start + EMBEDDING_BATCH_SIZE]
        payload = {
            "model": EMBEDDING_MODEL,
            "input": batch,
            "dimension": EMBEDDING_DIMENSION,
            "encoding_format": "float",
        }
        resp = requests.post(EMBEDDING_API_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data") or []
        if len(data) != len(batch):
            raise RuntimeError("Embedding 返回数量与输入不一致")
        for item in data:
            vec = item.get("embedding")
            if not isinstance(vec, list):
                raise RuntimeError("Embedding 响应格式错误")
            vectors.append(vec)
    return vectors


def insert_knowledge(atoms: List[Dict]):
    """
    直接将提取到的原子知识列表存入 ES
    
    Args:
        atoms: 原子知识字典列表，每个字典应包含 match_tokens, advice, category, source_file, page_num 等字段
    """
    if not atoms:
        return

    es = init_es()
    
    # 提取后立即向量化并写入 ES
    advice_texts = [(a.get("advice") or "").strip() for a in atoms]
    vectors = _embed_texts(advice_texts)

    actions = []
    for i, atom in enumerate(atoms):
        doc = dict(atom)
        doc["vector"] = vectors[i]
        doc["model_version"] = EMBEDDING_MODEL
        actions.append({
            "_index": INDEX_NAME,
            "_source": doc
        })
    
    # 批量写入，不等待索引刷新以提高性能
    success, errors = helpers.bulk(es, actions, refresh=False, raise_on_error=False)
    if errors:
        print(f"  [ES写入] 部分失败: {len(errors)} 条")
    print(f"  [ES写入] 成功入库 {success} 条")


# ========== 以下为独立运行时的批量导入功能 ==========

def read_jsonl_files(directory: str) -> List[Dict]:
    """读取目录下所有 JSONL 文件"""
    all_docs = []
    
    if not os.path.exists(directory):
        print(f"警告：目录 '{directory}' 不存在")
        return all_docs
    
    jsonl_files = [f for f in os.listdir(directory) if f.endswith('.jsonl')]
    
    if not jsonl_files:
        print(f"警告：在 '{directory}' 中未找到 .jsonl 文件")
        return all_docs
    
    print(f"发现 {len(jsonl_files)} 个 JSONL 文件")
    
    for filename in jsonl_files:
        filepath = os.path.join(directory, filename)
        print(f"读取文件: {filename}...")
        
        with open(filepath, 'r', encoding='utf-8') as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                
                try:
                    doc = json.loads(line)
                    # 添加来源文件信息（如果记录中没有）
                    if 'source_file' not in doc:
                        doc['source_file'] = filename
                    all_docs.append(doc)
                except json.JSONDecodeError as e:
                    print(f"  警告：文件 {filename} 第 {line_no} 行 JSON 解析失败: {e}")
                    continue
        
        print(f"  ✓ 读取到 {len([d for d in all_docs if d['source_file'] == filename])} 条记录")
    
    return all_docs


def bulk_index_documents(es: Elasticsearch, index_name: str, documents: List[Dict], batch_size: int = 500):
    """批量写入文档到 ES"""
    if not documents:
        print("没有文档需要写入")
        return
    
    print(f"\n开始批量写入 {len(documents)} 条文档到索引 '{index_name}'...")
    
    # 准备批量操作
    actions = [
        {
            "_index": index_name,
            "_source": doc
        }
        for doc in documents
    ]
    
    # 批量写入
    success, failed = 0, 0
    for ok, response in helpers.streaming_bulk(
        es,
        actions,
        chunk_size=batch_size,
        raise_on_error=False
    ):
        if ok:
            success += 1
        else:
            failed += 1
            print(f"  写入失败: {response}")
        
        # 每 100 条显示一次进度
        if (success + failed) % 100 == 0:
            print(f"  进度: {success + failed}/{len(documents)}")
    
    print(f"\n✓ 写入完成！成功: {success}, 失败: {failed}")


def main():
    """独立运行时的主函数：从 JSONL 文件批量导入"""
    try:
        # 1. 初始化 ES（会自动连接并创建索引）
        init_es()
        
        # 2. 读取所有 JSONL 文件
        documents = read_jsonl_files(KNOWLEDGE_DIR)
        
        if not documents:
            print("\n未找到任何文档，退出")
            return
        
        print(f"\n总共读取到 {len(documents)} 条知识记录")
        
        # 3. 批量写入 ES
        bulk_index_documents(ES_CLIENT, INDEX_NAME, documents, BATCH_SIZE)
        
        # 4. 刷新索引确保数据可见
        ES_CLIENT.indices.refresh(index=INDEX_NAME)
        
        # 5. 验证写入
        count = ES_CLIENT.count(index=INDEX_NAME)['count']
        print(f"\n索引 '{INDEX_NAME}' 当前文档总数: {count}")
        
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
