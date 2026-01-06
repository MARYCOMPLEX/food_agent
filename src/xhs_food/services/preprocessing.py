"""
评论预处理服务 - Comment Preprocessing Service.

负责：
1. 从评论中提取点赞数（正则匹配 "[112赞]" 格式）
2. 计算 interaction_score
3. 返回清洗后的评论列表供 LLM 分析
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ProcessedComment:
    """预处理后的评论数据."""
    
    id: str
    text: str
    likes: int = 0
    interaction_score: float = 1.0
    sub_comment_count: int = 0
    user_name: str = ""


def extract_likes_from_text(text: str) -> tuple[str, int]:
    """
    从评论文本中提取点赞数.
    
    支持格式:
    - "[112赞]"
    - "[1.2k赞]" / "[1.2K赞]"
    - "[1w赞]" / "[1W赞]" / "[1万赞]"
    
    Args:
        text: 原始评论文本
        
    Returns:
        tuple[str, int]: (清洗后的文本, 点赞数)
    """
    # 匹配 [数字赞] 或 [数字k/w赞] 格式
    patterns = [
        (r'\[(\d+(?:\.\d+)?)[kK]赞\]', lambda m: int(float(m.group(1)) * 1000)),
        (r'\[(\d+(?:\.\d+)?)[wW万]赞\]', lambda m: int(float(m.group(1)) * 10000)),
        (r'\[(\d+)赞\]', lambda m: int(m.group(1))),
    ]
    
    likes = 0
    cleaned_text = text
    
    for pattern, extractor in patterns:
        match = re.search(pattern, text)
        if match:
            likes = extractor(match)
            # 移除点赞标记
            cleaned_text = re.sub(pattern, '', text).strip()
            break
    
    return cleaned_text, likes


def calculate_interaction_score(likes: int, sub_comment_count: int = 0) -> float:
    """
    计算互动系数.
    
    规则:
    - 点赞 > 50: 2.0
    - 点赞 20-50: 1.5
    - 点赞 5-20: 1.2
    - 其他: 1.0
    - 子评论 > 10 时额外 ×1.5
    
    Args:
        likes: 点赞数
        sub_comment_count: 子评论数量
        
    Returns:
        float: 互动系数
    """
    if likes > 50:
        base_score = 2.0
    elif likes >= 20:
        base_score = 1.5
    elif likes >= 5:
        base_score = 1.2
    else:
        base_score = 1.0
    
    # 子评论加成
    if sub_comment_count > 10:
        base_score *= 1.5
    
    return base_score


def preprocess_comments(
    comments: List[Dict[str, Any]],
    max_comments: int = 30,
) -> List[ProcessedComment]:
    """
    批量预处理评论.
    
    Args:
        comments: 原始评论列表，每项可能包含:
            - text/content: 评论内容
            - likes/like_count: 点赞数
            - sub_comment_count: 子评论数
            - user/user_name: 用户名
        max_comments: 最大处理评论数
        
    Returns:
        List[ProcessedComment]: 预处理后的评论列表
    """
    processed = []
    
    for idx, comment in enumerate(comments[:max_comments]):
        # 获取评论文本
        text = comment.get('text') or comment.get('content') or ''
        if not text:
            continue
        
        # 尝试从文本中提取点赞数
        cleaned_text, text_likes = extract_likes_from_text(text)
        
        # 优先使用结构化的 likes 字段
        likes = comment.get('likes') or comment.get('like_count') or text_likes
        if isinstance(likes, str):
            try:
                likes = int(likes)
            except ValueError:
                likes = 0
        
        # 获取子评论数
        sub_count = comment.get('sub_comment_count') or comment.get('sub_comments', 0)
        if isinstance(sub_count, str):
            try:
                sub_count = int(sub_count)
            except ValueError:
                sub_count = 0
        
        # 计算互动分数
        interaction_score = calculate_interaction_score(likes, sub_count)
        
        processed.append(ProcessedComment(
            id=f"c{idx}",
            text=cleaned_text if cleaned_text else text,
            likes=likes,
            interaction_score=interaction_score,
            sub_comment_count=sub_count,
            user_name=comment.get('user') or comment.get('user_name') or '',
        ))
    
    return processed


def format_comments_for_llm(processed_comments: List[ProcessedComment]) -> str:
    """
    将预处理后的评论格式化为 LLM 输入.
    
    Args:
        processed_comments: 预处理后的评论列表
        
    Returns:
        str: 格式化的评论文本
    """
    lines = []
    for pc in processed_comments:
        line = f"[{pc.id}] {pc.text}"
        if pc.user_name:
            line = f"[{pc.id}] ({pc.user_name}) {pc.text}"
        lines.append(line)
    
    return "\n".join(lines)
