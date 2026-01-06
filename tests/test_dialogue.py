"""
本地多轮对话测试脚本 - Local Multi-turn Dialogue Test.

直接调用 XHSFoodOrchestrator，无需启动服务器。
支持交互式对话测试。
"""

import sys
sys.path.insert(0, "src")

import asyncio
import logging

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()

from xhs_food import XHSFoodOrchestrator

# 设置日志级别
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)


async def run_single_query(query: str):
    """执行单次查询（无对话上下文）."""
    print(f"\n{'='*60}")
    print(f"查询: {query}")
    print("="*60)
    
    orchestrator = XHSFoodOrchestrator()
    result = await orchestrator.search(query)
    
    print(f"\n状态: {result.status}")
    print(f"摘要: {result.summary}")
    
    if result.recommendations:
        print(f"\n推荐店铺 ({len(result.recommendations)} 家):")
        for i, rec in enumerate(result.recommendations, 1):
            wa = rec.wanghong_analysis
            score = wa.score.value if wa else "unknown"
            print(f"  {i}. {rec.name} [{score}] - {', '.join(rec.features[:3])}")
    
    if result.filtered_count:
        print(f"\n过滤了 {result.filtered_count} 家网红店")
    
    return result


async def run_multi_turn_dialogue(deep_search: bool = True):
    """交互式多轮对话测试."""
    mode_label = "深度研究" if deep_search else "快速"
    print("\n" + "="*60)
    print(f"XHS Food Agent - 多轮对话测试 [{mode_label}模式]")
    print("="*60)
    print("输入搜索请求开始对话，支持追问（如\"排除XX\"、\"还有吗\"、\"想吃点XX类的\"）")
    print("输入 'quit' 退出，输入 'reset' 重置对话")
    print("="*60 + "\n")
    
    orchestrator = XHSFoodOrchestrator(deep_search=deep_search)
    
    while True:
        try:
            user_input = input("\n你: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\n再见！")
            break
        
        if not user_input:
            continue
        
        if user_input.lower() == "quit":
            print("再见！")
            break
        
        if user_input.lower() == "reset":
            orchestrator.reset_context()
            print("对话已重置")
            continue
        
        try:
            result = await orchestrator.search(user_input)
            
            print(f"\n[状态: {result.status}]")
            
            if result.status == "clarify":
                print("需要澄清:")
                for q in result.clarify_questions or []:
                    print(f"  - {q}")
            elif result.status == "error":
                print(f"错误: {result.error_message}")
            else:
                print(f"\n{result.summary}")
                
                if result.recommendations:
                    print(f"\n推荐店铺 ({len(result.recommendations)} 家):")
                    for i, rec in enumerate(result.recommendations, 1):
                        wa = rec.wanghong_analysis
                        score = wa.score.value if wa else "unknown"
                        confidence = rec.confidence
                        print(f"  {i}. {rec.name}")
                        print(f"     判定: {score} (置信度: {confidence:.0%})")
                        if rec.features:
                            print(f"     特点: {', '.join(rec.features[:3])}")
                        if rec.location:
                            print(f"     位置: {rec.location}")
                
                if result.filtered_count:
                    print(f"\n(过滤了 {result.filtered_count} 家网红店)")
                
                # 显示对话上下文
                ctx = orchestrator.context
                print(f"\n[对话轮次: {ctx.turn_count}]")
                
        except Exception as e:
            logging.exception("处理请求时发生错误")
            print(f"错误: {e}")


async def run_preset_dialogue():
    """预设对话流程测试."""
    print("\n" + "="*60)
    print("预设对话流程测试")
    print("="*60)
    
    orchestrator = XHSFoodOrchestrator()
    
    # 预设对话
    dialogues = [
        "搜索蒙自本地人常去的老店",
        # "排除叶小辣",  # 过滤
        # "还有吗",       # 扩展
        # "第一家怎么样", # 详情
    ]
    
    for i, query in enumerate(dialogues, 1):
        print(f"\n{'='*60}")
        print(f"[轮次 {i}] 用户: {query}")
        print("="*60)
        
        result = await orchestrator.search(query)
        
        print(f"\n状态: {result.status}")
        print(f"摘要: {result.summary}")
        
        if result.recommendations:
            print(f"\n推荐店铺 ({len(result.recommendations)} 家):")
            for j, rec in enumerate(result.recommendations, 1):
                wa = rec.wanghong_analysis
                score = wa.score.value if wa else "unknown"
                print(f"  {j}. {rec.name} [{score}]")
                if rec.features:
                    print(f"     特点: {', '.join(rec.features[:2])}")
        
        print(f"\n当前上下文店铺数: {len(orchestrator.context.last_recommendations)}")
        
        # 等待一下避免请求过快
        await asyncio.sleep(1)
    
    print("\n" + "="*60)
    print("对话测试完成")
    print("="*60)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="XHS Food Agent 本地测试")
    parser.add_argument(
        "--mode", 
        choices=["interactive", "preset", "single"],
        default="interactive",
        help="测试模式: interactive(交互式), preset(预设对话), single(单次查询)"
    )
    parser.add_argument(
        "--query",
        type=str,
        default="搜索蒙自本地人常去的老店",
        help="单次查询模式的查询内容"
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="快速模式（最多搜索10篇笔记，默认为深度研究模式）"
    )
    
    args = parser.parse_args()
    deep_search = not args.fast
    
    if args.mode == "interactive":
        asyncio.run(run_multi_turn_dialogue(deep_search=deep_search))
    elif args.mode == "preset":
        asyncio.run(run_preset_dialogue())
    else:
        asyncio.run(run_single_query(args.query))
