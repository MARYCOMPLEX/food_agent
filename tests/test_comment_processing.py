"""
评论处理模块单元测试 - Comment Processing Unit Tests.

验证:
1. 点赞数提取的正确性
2. interaction_score 计算的边界值
3. 最终得分计算的精确性 (确保 Python 计算无误)
"""

import sys
sys.path.insert(0, "src")

# pytest is optional - tests can run directly via __main__
try:
    import pytest
except ImportError:
    pytest = None

from xhs_food.services.preprocessing import (
    extract_likes_from_text,
    calculate_interaction_score,
    preprocess_comments,
    ProcessedComment,
)
from xhs_food.services.scoring import (
    calculate_comment_score,
    calculate_scores,
    get_content_coefficient,
    get_identity_coefficient,
    CommentAnalysis,
    ShopScore,
)


# =============================================================================
# 预处理测试
# =============================================================================

class TestExtractLikesFromText:
    """测试点赞数提取."""
    
    def test_basic_likes(self):
        """基本点赞格式."""
        text, likes = extract_likes_from_text("很好吃[112赞]")
        assert likes == 112
        assert text == "很好吃"
    
    def test_k_format(self):
        """千位格式 (1.2k)."""
        text, likes = extract_likes_from_text("[1.2k赞]推荐这家")
        assert likes == 1200
        assert "推荐这家" in text
    
    def test_w_format(self):
        """万位格式 (1w/1.5万)."""
        text, likes = extract_likes_from_text("太赞了[2w赞]")
        assert likes == 20000
        
        text2, likes2 = extract_likes_from_text("好吃[1.5万赞]")
        assert likes2 == 15000
    
    def test_no_likes(self):
        """无点赞标记."""
        text, likes = extract_likes_from_text("这家店不错")
        assert likes == 0
        assert text == "这家店不错"


class TestCalculateInteractionScore:
    """测试互动系数计算."""
    
    def test_high_likes(self):
        """点赞 > 50 -> 2.0"""
        assert calculate_interaction_score(51) == 2.0
        assert calculate_interaction_score(100) == 2.0
        assert calculate_interaction_score(1000) == 2.0
    
    def test_medium_high_likes(self):
        """20 <= 点赞 <= 50 -> 1.5"""
        assert calculate_interaction_score(20) == 1.5
        assert calculate_interaction_score(35) == 1.5
        assert calculate_interaction_score(50) == 1.5
    
    def test_medium_likes(self):
        """5 <= 点赞 < 20 -> 1.2"""
        assert calculate_interaction_score(5) == 1.2
        assert calculate_interaction_score(10) == 1.2
        assert calculate_interaction_score(19) == 1.2
    
    def test_low_likes(self):
        """点赞 < 5 -> 1.0"""
        assert calculate_interaction_score(0) == 1.0
        assert calculate_interaction_score(1) == 1.0
        assert calculate_interaction_score(4) == 1.0
    
    def test_sub_comment_bonus(self):
        """子评论加成 (>10 -> ×1.5)."""
        # 基础分 2.0，子评论加成后 3.0
        assert calculate_interaction_score(51, sub_comment_count=11) == 3.0
        # 子评论不足不加成
        assert calculate_interaction_score(51, sub_comment_count=5) == 2.0


class TestPreprocessComments:
    """测试批量预处理."""
    
    def test_basic_preprocessing(self):
        """基本预处理流程."""
        comments = [
            {"text": "很好吃[50赞]", "likes": 50},
            {"text": "一般般", "likes": 2},
        ]
        
        result = preprocess_comments(comments)
        
        assert len(result) == 2
        assert result[0].id == "c0"
        assert result[0].interaction_score == 1.5  # 20-50
        assert result[1].interaction_score == 1.0  # <5
    
    def test_text_likes_fallback(self):
        """从文本提取点赞（字段不存在时）."""
        comments = [
            {"text": "推荐[100赞]"},
        ]
        
        result = preprocess_comments(comments)
        
        assert result[0].likes == 100
        assert result[0].interaction_score == 2.0


# =============================================================================
# 计分测试
# =============================================================================

class TestCoefficientCalculation:
    """测试系数计算."""
    
    def test_identity_coefficient(self):
        """身份系数映射."""
        assert get_identity_coefficient("strong") == 3.0
        assert get_identity_coefficient("medium") == 2.0
        assert get_identity_coefficient("none") == 1.0
        assert get_identity_coefficient("unknown") == 1.0  # 默认值
    
    def test_content_coefficient_correction(self):
        """纠正类评论系数."""
        # is_correction=True 时固定为 3.0
        assert get_content_coefficient(True, "positive") == 3.0
        assert get_content_coefficient(True, "negative") == 3.0
        assert get_content_coefficient(True, "neutral") == 3.0
    
    def test_content_coefficient_sentiment(self):
        """情感系数（非纠正类）."""
        assert get_content_coefficient(False, "negative") == 1.5
        assert get_content_coefficient(False, "positive") == 1.0
        assert get_content_coefficient(False, "neutral") == 1.0


class TestFinalScoreCalculation:
    """测试最终得分计算 - 确保 Python 计算精确."""
    
    def test_score_formula(self):
        """验证公式: Score = interaction × identity × content."""
        processed = ProcessedComment(
            id="c0",
            text="作为成都人很推荐",
            likes=60,
            interaction_score=2.0,  # >50
        )
        
        analysis = CommentAnalysis(
            id="c0",
            identity="strong",       # ×3.0
            sentiment="positive",
            is_correction=True,      # ×3.0
            mentioned_shops=["老店A"],
        )
        
        result = calculate_comment_score(processed, analysis)
        
        # 2.0 × 3.0 × 3.0 = 18.0
        assert result.final_score == 18.0
        assert result.interaction_score == 2.0
        assert result.identity_coefficient == 3.0
        assert result.content_coefficient == 3.0
    
    def test_avoid_llm_arithmetic_error(self):
        """确保不会出现 LLM 常见的 3×1.5=6 错误."""
        processed = ProcessedComment(
            id="c1",
            text="测试",
            likes=25,
            interaction_score=1.5,  # 20-50
        )
        
        analysis = CommentAnalysis(
            id="c1",
            identity="strong",       # ×3.0
            sentiment="positive",
            is_correction=False,     # ×1.0
            mentioned_shops=[],
        )
        
        result = calculate_comment_score(processed, analysis)
        
        # 正确: 1.5 × 3.0 × 1.0 = 4.5
        # LLM 可能错误计算为 6.0 (3×1.5=6)
        assert result.final_score == 4.5, f"Expected 4.5, got {result.final_score}"


class TestCalculateScores:
    """测试店铺得分汇总."""
    
    def test_shop_aggregation(self):
        """测试店铺得分聚合."""
        llm_results = [
            {"id": "c0", "identity": "strong", "sentiment": "positive", 
             "is_correction": False, "mentioned_shops": ["老店A"]},
            {"id": "c1", "identity": "medium", "sentiment": "positive",
             "is_correction": False, "mentioned_shops": ["老店A", "老店B"]},
        ]
        
        preprocessed = [
            ProcessedComment(id="c0", text="t1", likes=60, interaction_score=2.0),
            ProcessedComment(id="c1", text="t2", likes=25, interaction_score=1.5),
        ]
        
        result = calculate_scores(llm_results, preprocessed)
        
        assert "老店A" in result
        assert "老店B" in result
        
        # 老店A: 被 c0 和 c1 提及
        # c0: 2.0 × 3.0 × 1.0 = 6.0
        # c1: 1.5 × 2.0 × 1.0 = 3.0
        # 总分: 9.0
        assert result["老店A"].total_score == 9.0
        assert result["老店A"].mention_count == 2


# =============================================================================
# 运行测试
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("评论处理模块单元测试")
    print("=" * 60)
    
    # 预处理测试
    print("\n[1/4] 测试点赞提取...")
    test_extract = TestExtractLikesFromText()
    test_extract.test_basic_likes()
    test_extract.test_k_format()
    test_extract.test_w_format()
    test_extract.test_no_likes()
    print("  ✓ 点赞提取测试通过")
    
    print("\n[2/4] 测试互动系数计算...")
    test_interaction = TestCalculateInteractionScore()
    test_interaction.test_high_likes()
    test_interaction.test_medium_high_likes()
    test_interaction.test_medium_likes()
    test_interaction.test_low_likes()
    test_interaction.test_sub_comment_bonus()
    print("  ✓ 互动系数测试通过")
    
    print("\n[3/4] 测试系数映射...")
    test_coeff = TestCoefficientCalculation()
    test_coeff.test_identity_coefficient()
    test_coeff.test_content_coefficient_correction()
    test_coeff.test_content_coefficient_sentiment()
    print("  ✓ 系数映射测试通过")
    
    print("\n[4/4] 测试最终得分计算...")
    test_score = TestFinalScoreCalculation()
    test_score.test_score_formula()
    test_score.test_avoid_llm_arithmetic_error()
    print("  ✓ 最终得分测试通过")
    
    print("\n" + "=" * 60)
    print("✅ 所有测试通过！Python 计算逻辑验证成功。")
    print("=" * 60)
