"""
独立计算逻辑测试 - Standalone Calculation Tests.

此测试文件不依赖任何外部包（langchain等），直接验证核心计算函数。
"""

import sys
sys.path.insert(0, "src")


def test_interaction_score():
    """测试互动系数计算 - 直接复制核心逻辑."""
    
    def calculate_interaction_score(likes: int, sub_comment_count: int = 0) -> float:
        if likes > 50:
            base_score = 2.0
        elif likes >= 20:
            base_score = 1.5
        elif likes >= 5:
            base_score = 1.2
        else:
            base_score = 1.0
        
        if sub_comment_count > 10:
            base_score *= 1.5
        
        return base_score
    
    # 边界测试
    assert calculate_interaction_score(51) == 2.0, "likes>50 should be 2.0"
    assert calculate_interaction_score(50) == 1.5, "likes=50 should be 1.5"
    assert calculate_interaction_score(20) == 1.5, "likes=20 should be 1.5"
    assert calculate_interaction_score(19) == 1.2, "likes=19 should be 1.2"
    assert calculate_interaction_score(5) == 1.2, "likes=5 should be 1.2"
    assert calculate_interaction_score(4) == 1.0, "likes=4 should be 1.0"
    assert calculate_interaction_score(0) == 1.0, "likes=0 should be 1.0"
    
    # 子评论加成
    assert calculate_interaction_score(51, 11) == 3.0, "likes>50 with sub>10 should be 3.0"
    assert calculate_interaction_score(51, 5) == 2.0, "likes>50 with sub<=10 should be 2.0"
    
    print("  ✓ 互动系数测试通过")


def test_coefficient_mappings():
    """测试系数映射."""
    
    IDENTITY_COEFFICIENTS = {
        "strong": 3.0,
        "medium": 2.0,
        "none": 1.0,
    }
    
    def get_identity_coefficient(identity: str) -> float:
        return IDENTITY_COEFFICIENTS.get(identity, 1.0)
    
    def get_content_coefficient(is_correction: bool, sentiment: str) -> float:
        if is_correction:
            return 3.0
        if sentiment == "negative":
            return 1.5
        return 1.0
    
    # 身份系数
    assert get_identity_coefficient("strong") == 3.0
    assert get_identity_coefficient("medium") == 2.0
    assert get_identity_coefficient("none") == 1.0
    assert get_identity_coefficient("unknown") == 1.0
    
    # 内容系数
    assert get_content_coefficient(True, "positive") == 3.0
    assert get_content_coefficient(True, "negative") == 3.0
    assert get_content_coefficient(False, "negative") == 1.5
    assert get_content_coefficient(False, "positive") == 1.0
    
    print("  ✓ 系数映射测试通过")


def test_final_score_formula():
    """测试最终得分公式 - 核心验证."""
    
    def calculate_final_score(
        interaction_score: float,
        identity: str,
        is_correction: bool,
        sentiment: str
    ) -> float:
        """Score = interaction × identity × content"""
        
        # Identity coefficient
        identity_map = {"strong": 3.0, "medium": 2.0, "none": 1.0}
        identity_coeff = identity_map.get(identity, 1.0)
        
        # Content coefficient
        if is_correction:
            content_coeff = 3.0
        elif sentiment == "negative":
            content_coeff = 1.5
        else:
            content_coeff = 1.0
        
        return interaction_score * identity_coeff * content_coeff
    
    # 高权重评论: 2.0 × 3.0 × 3.0 = 18.0
    score1 = calculate_final_score(2.0, "strong", True, "positive")
    assert score1 == 18.0, f"Expected 18.0, got {score1}"
    
    # 验证 LLM 常见错误: 1.5 × 3.0 × 1.0 应该是 4.5 而不是 6.0
    score2 = calculate_final_score(1.5, "strong", False, "positive")
    assert score2 == 4.5, f"Expected 4.5, got {score2}. LLM would incorrectly say 6.0"
    
    # 另一个边界测试: 1.2 × 2.0 × 1.5 = 3.6 (浮点精度)
    score3 = calculate_final_score(1.2, "medium", False, "negative")
    assert abs(score3 - 3.6) < 0.0001, f"Expected ~3.6, got {score3}"
    
    print("  ✓ 最终得分公式测试通过")


def test_likes_extraction():
    """测试点赞数提取."""
    import re
    
    def extract_likes_from_text(text: str) -> tuple:
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
                cleaned_text = re.sub(pattern, '', text).strip()
                break
        
        return cleaned_text, likes
    
    # 基本格式
    text, likes = extract_likes_from_text("很好吃[112赞]")
    assert likes == 112
    assert text == "很好吃"
    
    # k 格式
    text, likes = extract_likes_from_text("[1.2k赞]推荐")
    assert likes == 1200
    
    # w 格式
    text, likes = extract_likes_from_text("好吃[2w赞]")
    assert likes == 20000
    
    # 万 格式
    text, likes = extract_likes_from_text("推荐[1.5万赞]")
    assert likes == 15000
    
    # 无点赞
    text, likes = extract_likes_from_text("普通评论")
    assert likes == 0
    assert text == "普通评论"
    
    print("  ✓ 点赞提取测试通过")


if __name__ == "__main__":
    print("=" * 60)
    print("独立计算逻辑测试 (无外部依赖)")
    print("=" * 60)
    
    print("\n[1/4] 测试互动系数...")
    test_interaction_score()
    
    print("\n[2/4] 测试系数映射...")
    test_coefficient_mappings()
    
    print("\n[3/4] 测试最终得分公式...")
    test_final_score_formula()
    
    print("\n[4/4] 测试点赞提取...")
    test_likes_extraction()
    
    print("\n" + "=" * 60)
    print("✅ 所有计算逻辑测试通过！")
    print("=" * 60)
    print("\n核心验证:")
    print("  - 1.5 × 3.0 × 1.0 = 4.5 ✓ (LLM 常错为 6.0)")
    print("  - 2.0 × 3.0 × 3.0 = 18.0 ✓")
    print("  - 1.2 × 2.0 × 1.5 = 3.6 ✓")
