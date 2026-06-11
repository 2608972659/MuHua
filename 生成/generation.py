import os
import json
import traceback
from typing import Optional, Dict, Any

from query import query
from advice import get_advice

file_path = os.path.dirname(__file__)

# 从环境变量读取 DeepSeek API 配置，不再硬编码密钥
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")


class Generation:
    def __init__(self, patient_profile: Dict[str, Any], summary_info: Dict[str, Any],
                 advice_cache: Dict[str, Any] = None) -> None:
        self.patient_profile = patient_profile
        self.summary_info = summary_info
        # ES 检索结果缓存：advice_type → hits 列表，外部传入可避免重复查询
        self._advice_cache = advice_cache or {}

    def _get_advice_cached(self, advice_type: str) -> list:
        """从缓存获取 ES 检索结果，缓存未命中时实时查询。"""
        if advice_type in self._advice_cache:
            return self._advice_cache[advice_type]
        return get_advice(self.summary_info, advice_type)

    def assemble_prompt(self, type: str, advice: str) -> list:
        prompt_path = os.path.join(file_path, "prompts")
        system_prompt_filepath = os.path.join(prompt_path, f"{type}.json")
        with open(system_prompt_filepath, "r", encoding="utf-8") as f:
            system_prompt = json.load(f)

        prompt = [
            "\n".join(system_prompt["role"]),
            "\n".join(system_prompt["patient_profile"]).format(patient_profile=self.patient_profile),
            "\n".join(system_prompt["input_advice"]).format(advice=advice),
            "\n".join(system_prompt["output_format"]),
        ]
        return prompt

    def _generate(self, advice_type: str) -> Optional[str]:
        try:
            advice = self._get_advice_cached(advice_type)
            prompt = self.assemble_prompt(advice_type, advice)
            return query(DEEPSEEK_API_KEY, DEEPSEEK_API_URL, DEEPSEEK_MODEL, prompt)
        except Exception as e:
            print(f"Error in {advice_type} function: {repr(e)}  type={type(e)}")
            traceback.print_exc()
            return None

    def lifestyle(self) -> Optional[str]:
        return self._generate("健康生活方式")

    def treatment(self) -> Optional[str]:
        return self._generate("治疗与康复")

    def emergency(self) -> Optional[str]:
        return self._generate("急症处理")
