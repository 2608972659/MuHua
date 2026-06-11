import os, re, json, time
from typing import List, Dict, Iterable
from dataclasses import dataclass

# OCR 相关依赖：只在扫描型 PDF 时才需要
import pytesseract

import fitz  # PyMuPDF

from PIL import Image, ImageOps
from query import query

# 引入 ES 相关函数
from load_to_es import init_es, insert_knowledge

# --------- CONFIG ----------

TEMPERATURE = 0.1
MAX_TOKENS = 1200

# For simple rate control
SLEEP_BETWEEN_CALLS = 0.2

# 每个源文件的未筛选提取建议保存目录
UNSCREENED_DIR_NAME = "未筛选"


def save_unscreened_suggestions(source_file: str, suggestions: List[Dict]):
    """将单个源文件的未筛选建议保存为 JSONL。"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, UNSCREENED_DIR_NAME)
    os.makedirs(output_dir, exist_ok=True)

    output_path = os.path.join(output_dir, f"{source_file}.jsonl")

    with open(output_path, "w", encoding="utf-8") as f:
        for item in suggestions:
            row = dict(item)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"  [未筛选保存] 已写入: {output_path} ({len(suggestions)} 条)")

# --------- UTILITIES ----------

def _chunk_text(text: str, max_chars: int = 2000) -> List[str]:
    """将长文本切成若干段，尽量按自然段落拼接，避免单段过长。"""
    text = (text or "").strip()
    if not text:
        return []

    # PDF 经常包含分页符 \f；如果有就优先按“页”切
    if "\f" in text:
        parts = [p.strip() for p in text.split("\f")]
        return [p for p in parts if p]

    paragraphs = [p.strip() for p in text.splitlines()]
    paragraphs = [p for p in paragraphs if p]

    chunks: List[str] = []
    buf: List[str] = []
    buf_len = 0
    for para in paragraphs:
        # +1 代表拼接时的换行
        para_len = len(para) + 1
        if buf and (buf_len + para_len) > max_chars:
            chunks.append("\n".join(buf).strip())
            buf = [para]
            buf_len = len(para)
        else:
            buf.append(para)
            buf_len += para_len

    if buf:
        chunks.append("\n".join(buf).strip())

    return [c for c in chunks if c]


def _non_space_len(s: str) -> int:
    return len(re.sub(r"\s+", "", s or ""))


def _looks_like_scanned_pdf(chunks: List[str], min_chars_per_page: int = 30, threshold: float = 0.7) -> bool:
    """基于“每页可提取文本量”粗略判断是否为扫描型 PDF。

    - chunks 通常来自按 \f 分页后的页面文本
    - 若多数页面（占比 >= threshold）的非空白字符数 < min_chars_per_page，则认为是扫描型
    """
    if not chunks:
        return True

    scanned_like_pages = 0
    for t in chunks:
        if _non_space_len(t) < min_chars_per_page:
            scanned_like_pages += 1
    return (scanned_like_pages / max(len(chunks), 1)) >= threshold


def ocr_pdf_with_tesseract(
    path: str,
    lang: str = "chi_sim",
    dpi: int = 300,
) -> List[Dict]:
    """对扫描型 PDF 做 OCR，返回 [{'page': 1, 'text': '...'}, ...]。"""

    zoom = dpi / 72.0  # PDF 1 point = 1/72 inch
    mat = fitz.Matrix(zoom, zoom)
    doc = fitz.open(path)

    out: List[Dict] = []
    for i in range(len(doc)):
        page = doc[i]
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

        # 轻量预处理：转灰度 + 自动对比度（不改变抽取逻辑，仅提升 OCR 可用性）
        if ImageOps is not None:
            img = ImageOps.grayscale(img)
            img = ImageOps.autocontrast(img)

        text = pytesseract.image_to_string(img, lang=lang) or ""
        text = text.strip()
        print(f"OCR 第 {i + 1} 页提取到 {len(text)} 字符")
        if text:
            out.append({"page": i + 1, "text": text})
        else:
            out.append({"page": i + 1, "text": ""})
    return out


def read_doc_with_pages(path: str) -> List[Dict]:
    """
    不依赖 Tika：
    - PDF 使用 PyMuPDF 按页提取，必要时 OCR 兜底
    - 纯文本类文件按文本读取后切块（page 为段序号）
    返回形如 [{'page': 1, 'text': '...'}, ...]

    注意：doc/docx/wps/ppt/xls 等 Office 文件不再支持，建议先转为 PDF。
    """
    ext = os.path.splitext(path)[1].lower()

    # 1) PDF 走 PyMuPDF 按页提取
    if ext == ".pdf":
        doc = fitz.open(path)
        page_chunks = []
        for i in range(len(doc)):
            text = (doc[i].get_text("text") or "").strip()
            page_chunks.append(text)

        if _looks_like_scanned_pdf(page_chunks):
            print("检测到疑似扫描型 PDF，自动启用 OCR（Tesseract）...")
            return ocr_pdf_with_tesseract(path)

        if page_chunks:
            return [{"page": i, "text": t} for i, t in enumerate(page_chunks, start=1)]

    # 2) 纯文本类文件走文本读取
    if ext in {".txt", ".rtf", ".html", ".htm"}:
        raw = None
        for enc in ("utf-8", "gbk", "latin-1"):
            try:
                with open(path, "r", encoding=enc) as f:
                    raw = f.read()
                break
            except Exception:
                continue

        if raw is None:
            raise RuntimeError(f"无法读取文本文件: {path}")

        chunks = _chunk_text(raw)
        return [{"page": i, "text": t} for i, t in enumerate(chunks, start=1)]

    raise RuntimeError(f"当前不支持文件类型: {ext}，请先转换为 PDF/TXT/HTML/RTF")

    return [{"page": i, "text": t} for i, t in enumerate(chunks, start=1)]

# "Specific enough" quick check: must contain numbers/units or imperative cues.
SPECIFIC_PATTERNS = [
    r"\d+\s*(kcal|千卡|kg|千克|cm|厘米|分钟|分/|小时|天|周|月|次|组|%|％|mmHg)",
    r"≥|≤|>|<|≈|～|~",
    r"(每周|每月|每日|每天|每次|至少|不超过|不少于)",
    r"(1RM|VO2R|HRR|MET|kcal/周|次/组|组/周)"
]
SPECIFIC_RE = re.compile("|".join(SPECIFIC_PATTERNS))

def looks_specific(s: str) -> bool:
    return bool(SPECIFIC_RE.search(s))

def quote_is_substring(quote: str, context: str) -> bool:
    return quote.strip() and quote.strip() in context



def call_extract(context_text: str) -> Dict[str, List[Dict]]:
    """Call model to extract JSONL lines from context_text.

    Returns:
        {
            "all_atoms": 仅按 JSON 可解析得到的候选（未经过 SPECIFIC_PATTERNS 过滤）,
            "filtered_atoms": 经过 SPECIFIC_PATTERNS 过滤后的候选
        }
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_path = os.path.join(script_dir, "prompt.json")
    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt_json = json.load(f)

    # SYSTEM_PROMPT 是一个 list[str]，用换行拼成一个长的 system prompt
    sys_prompt = "\n".join(prompt_json["task"])
    sys_prompt += "\n".join(prompt_json["requirements"])
    max_retries = 3

    # context_text 也是一个 list[str]，先 join 再 format
    ctx_template = "\n".join(prompt_json["context_text"])
    context_prompt = ctx_template.format(context=context_text)

    for attempt in range(1, max_retries + 1):
        try:
            res = query(system_prompt=sys_prompt, content=context_prompt)
            if isinstance(res, str):
                text = res
            else:
                text = str(res)

            #print(text)
            if isinstance(res, str):
                text = res
            elif isinstance(res, dict):
                # 常见 openai 风格
                text = (
                    res.get("content")
                    or res.get("message", {}).get("content")
                    or (res.get("choices") or [{}])[0].get("message", {}).get("content", "")
                )
            else:
                text = str(res)

            all_atoms: List[Dict] = []
            filtered_atoms: List[Dict] = []
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                line = line.strip("`")
                parsed = None
                try:
                    parsed = json.loads(line)
                except Exception:
                    try:
                        parsed = json.loads(line.rstrip(","))
                    except Exception:
                        parsed = None

                if not isinstance(parsed, dict):
                    continue

                all_atoms.append(parsed)
                if looks_specific(line):
                    filtered_atoms.append(parsed)

            return {
                "all_atoms": all_atoms,
                "filtered_atoms": filtered_atoms,
            }

        except Exception as e:
            print(f"[call_extract] 发生错误：{e}")
            if attempt < max_retries:
                print("[call_extract] 等待 2 秒后重试...")
                time.sleep(2)
            else:
                print("[call_extract] 已达到最大重试次数，跳过此页")
                return {
                    "all_atoms": [],
                    "filtered_atoms": [],
                }



def extract_from_pdf(path: str):
    """提取文档中的原子知识并存入 ES"""
    pages = read_doc_with_pages(path)
    title = os.path.basename(path)
    print(f"\n开始提取文档中的原子知识: {title}")
    
    total_extracted = 0
    unscreened_suggestions: List[Dict] = []
    for p in pages:
        page_no = p["page"]
        text = p["text"]
        
        if not text.strip():
            print(f"第 {page_no} 页为空，跳过")
            continue
            
        print(f"\n处理第 {page_no} 页...")
        extract_result = call_extract(text)
        raw_atoms = [a for a in extract_result.get("all_atoms", []) if a and a != {}]
        cleaned_atoms = [a for a in extract_result.get("filtered_atoms", []) if a and a != {}]

        for a in raw_atoms:
            unscreened_item = dict(a)
            unscreened_item["page_num"] = page_no
            unscreened_suggestions.append(unscreened_item)
        
        # 准备入库的数据列表
        if cleaned_atoms:
            to_insert = []
            for a in cleaned_atoms:
                # 添加来源和页码信息
                es_item = dict(a)
                es_item["source_file"] = title
                es_item["page_num"] = page_no
                to_insert.append(es_item)
            
            # 直接存入 ES
            try:
                insert_knowledge(to_insert)
                total_extracted += len(to_insert)
            except Exception as e:
                print(f"  [错误] 入库失败: {e}")

        time.sleep(SLEEP_BETWEEN_CALLS)

    # 每个源文件都保存一份未筛选建议 JSONL（即使为空）
    save_unscreened_suggestions(title, unscreened_suggestions)
    
    print(f"\n文档 {title} 处理完成，共提取 {total_extracted} 条知识")
    return total_extracted


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    folder = os.path.join(script_dir, "健康提示资源库")
    
    supported_exts = {".pdf", ".txt", ".rtf", ".html", ".htm"}
    
    print("="*60)
    print("健康知识提取入库")
    print("="*60)
    
    # 初始化 ES 连接
    try:
        print("\n[步骤 1] 初始化 Elasticsearch 连接...")
        init_es()
        print("✓ ES 连接初始化成功\n")
    except Exception as e:
        print(f"✗ ES 连接失败: {e}")
        print("请检查 Elasticsearch 服务是否启动，配置是否正确")
        exit(1)
    
    # 扫描文件夹
    print(f"[步骤 2] 扫描文件夹: {folder}")
    if not os.path.exists(folder):
        print(f"✗ 文件夹不存在: {folder}")
        exit(1)
    
    files_to_process = []
    for filename in os.listdir(folder):
        ext = os.path.splitext(filename)[1].lower()
        if ext in supported_exts:
            files_to_process.append(filename)
    
    if not files_to_process:
        print(f"✗ 在 {folder} 中未找到支持的文档文件")
        exit(0)
    
    print(f"✓ 找到 {len(files_to_process)} 个文档文件\n")
    
    # 处理每个文件
    print(f"[步骤 3] 开始提取并入库...")
    print("="*60)
    
    total_count = 0
    for i, filename in enumerate(files_to_process, 1):
        full_path = os.path.join(folder, filename)
        print(f"\n[{i}/{len(files_to_process)}] 处理文件: {filename}")
        
        try:
            count = extract_from_pdf(full_path)
            total_count += count
        except Exception as e:
            print(f"✗ 处理文件失败: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    # 最终刷新索引确保数据可搜索
    print("\n" + "="*60)
    print("[步骤 4] 刷新 ES 索引...")
    try:
        from load_to_es import ES_CLIENT, INDEX_NAME
        if ES_CLIENT:
            ES_CLIENT.indices.refresh(index=INDEX_NAME)
            final_count = ES_CLIENT.count(index=INDEX_NAME)['count']
            print(f"✓ 索引刷新成功")
            print(f"\n总结：")
            print(f"  - 处理文件数: {len(files_to_process)}")
            print(f"  - 本次提取: {total_count} 条")
            print(f"  - 索引总数: {final_count} 条")
    except Exception as e:
        print(f"✗ 刷新索引失败: {e}")
    
    print("\n" + "="*60)
    print("✓ 所有任务完成")
    print("="*60)
