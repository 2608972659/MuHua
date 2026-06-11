import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, Tuple, Optional
from generation import Generation


def parallel_generate_advice(
    patient_profile: Dict[str, Any],
    summary_info: Dict[str, Any],
    advice_cache: Dict[str, Any] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    并行调用 Generation 类的三个生成函数

    Args:
        patient_profile: 患者档案信息
        summary_info: 患者摘要信息
        advice_cache: ES 检索结果缓存，避免重复查询

    Returns:
        Tuple[Optional[str], Optional[str], Optional[str]]:
        返回 (lifestyle_result, treatment_result, emergency_result)
    """
    # 创建 Generation 实例
    gen = Generation(patient_profile, summary_info, advice_cache)
    
    # 定义要并行执行的任务     
    tasks = {
        'lifestyle': gen.lifestyle,
        'treatment': gen.treatment,
        'emergency': gen.emergency
    }
    
    # 存储结果
    results = {
        'lifestyle': None,
        'treatment': None,
        'emergency': None
    }
    
    # 使用 ThreadPoolExecutor 并行执行
    with ThreadPoolExecutor(max_workers=3) as executor:
        # 提交所有任务
        future_to_task = {
            executor.submit(func): task_name 
            for task_name, func in tasks.items()
        }
        
        # 收集结果
        for future in as_completed(future_to_task):
            task_name = future_to_task[future]
            try:
                result = future.result()
                results[task_name] = result
                print(f"完成")
            except Exception as e:
                print(f"执行失败: {e}")
                results[task_name] = None
    
    return results['lifestyle'], results['treatment'], results['emergency']


def parallel_generate_advice_with_timing(
    patient_profile: Dict[str, Any],
    summary_info: Dict[str, Any],
    advice_cache: Dict[str, Any] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str], float]:
    """
    并行调用 Generation 类的三个生成函数，并返回执行时间

    Args:
        patient_profile: 患者档案信息
        summary_info: 患者摘要信息
        advice_cache: ES 检索结果缓存，避免重复查询

    Returns:
        Tuple[Optional[str], Optional[str], Optional[str], float]:
        返回 (lifestyle_result, treatment_result, emergency_result, elapsed_time)
    """
    start_time = time.time()

    lifestyle_result, treatment_result, emergency_result = parallel_generate_advice(
        patient_profile, summary_info, advice_cache
    )
    
    elapsed_time = time.time() - start_time
    print(f"\n总执行时间: {elapsed_time:.2f} 秒")
    
    return lifestyle_result, treatment_result, emergency_result, elapsed_time

