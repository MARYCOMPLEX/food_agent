"""
XHSFoodOrchestrator - XHS 美食智能搜索主编排器 (支持多轮对话).

实现4阶段搜索策略 + 多轮对话支持：
1. 广撒网 - 建立候选店铺池
2. 挖隐藏 - 发现宝藏店铺
3. 定向验证 - 深挖具体店铺
4. 细分搜索 - 按品类深挖

多轮对话支持：
- 过滤类追问：排除某店、只要某类型
- 扩展类追问：多找几家、还有吗
- 详情类追问：XX店怎么样

使用示例:
    orchestrator = XHSFoodOrchestrator(...)
    
    # 第一轮搜索
    result1 = await orchestrator.search("搜索蒙自本地人常去的老店")
    
    # 第二轮追问
    result2 = await orchestrator.search("排除叶小辣")
    
    # 第三轮追问
    result3 = await orchestrator.search("还有吗")
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from xhs_food.agents.intent_parser import (
    IntentParserAgent,
    IntentParseResult,
)
from xhs_food.agents.analyzer import (
    AnalyzerAgent,
    AnalyzeResult,
)
from xhs_food.schemas import (
    FoodSearchIntent,
    RestaurantRecommendation,
    WanghongAnalysis,
    WanghongScore,
    XHSFoodResponse,
    SearchPhase,
    CrossValidationResult,
    RecommendationLevel,
    FollowUpType,
    ConversationContext,
)
from xhs_food.protocols.mcp import MCPToolRegistry

logger = logging.getLogger(__name__)


class XHSFoodOrchestrator:
    """
    XHS 美食智能搜索主编排器 (支持多轮对话).
    
    实现基于方法论的4阶段搜索策略，通过评论权重系统和交叉验证
    筛选出真正的本地老店，过滤网红店。
    
    支持多轮对话，可以根据用户追问进行过滤、扩展、详情查询等。
    """
    
    def __init__(
        self,
        *,
        xhs_registry: Optional[MCPToolRegistry] = None,
        intent_parser: Optional[IntentParserAgent] = None,
        analyzer: Optional[AnalyzerAgent] = None,
        llm_service=None,
    ):
        self._xhs_registry = xhs_registry
        self._intent_parser = intent_parser
        self._analyzer = analyzer
        self._llm_service = llm_service
        
        # 多轮对话上下文
        self._context = ConversationContext()
        
        # 缓存
        self._shop_mentions: Dict[str, List[str]] = {}
        self._analyzed_shops: Dict[str, RestaurantRecommendation] = {}
    
    async def _ensure_initialized(self) -> None:
        """确保所有组件初始化."""
        if self._intent_parser is None:
            self._intent_parser = IntentParserAgent(llm_service=self._llm_service)
        
        if self._analyzer is None:
            self._analyzer = AnalyzerAgent(llm_service=self._llm_service)
        
        if self._xhs_registry is None:
            from xhs_food.di.factories import get_xhs_tool_registry
            self._xhs_registry = get_xhs_tool_registry()
    
    def reset_context(self) -> None:
        """重置对话上下文（开始新会话）."""
        self._context.reset()
        self._shop_mentions = {}
        self._analyzed_shops = {}
    
    @property
    def context(self) -> ConversationContext:
        """获取当前对话上下文."""
        return self._context
    
    async def search(
        self,
        user_input: str,
    ) -> XHSFoodResponse:
        """
        执行搜索（推荐使用的多轮对话入口）.
        
        自动管理对话上下文，支持追问。
        
        Args:
            user_input: 用户输入
            
        Returns:
            XHSFoodResponse
        """
        return await self.process(user_input)
    
    async def process(
        self,
        user_input: str,
        *,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
    ) -> XHSFoodResponse:
        """
        处理用户请求，返回美食推荐.
        
        这是主入口方法，编排完整的美食搜索工作流。
        支持多轮对话，自动识别追问类型。
        """
        await self._ensure_initialized()
        
        try:
            # Step 1: 意图解析（带上下文）
            logger.info(f"[Step 1] 解析用户意图: {user_input[:50]}...")
            parse_result = await self._intent_parser.parse(user_input, self._context)
            
            if not parse_result.success:
                if parse_result.need_clarify:
                    return XHSFoodResponse(
                        status="clarify",
                        clarify_questions=parse_result.questions,
                        summary="需要更多信息以完成搜索",
                    )
                return XHSFoodResponse(
                    status="error",
                    error_message=parse_result.error or "意图解析失败",
                )
            
            follow_up_type = parse_result.follow_up_type
            logger.info(f"  追问类型: {follow_up_type.value}")
            
            # Step 2: 根据追问类型分发处理
            if follow_up_type == FollowUpType.FILTER:
                return await self._handle_filter(parse_result)
            
            elif follow_up_type == FollowUpType.EXPAND:
                return await self._handle_expand(parse_result)
            
            elif follow_up_type == FollowUpType.DETAIL:
                return await self._handle_detail(parse_result)
            
            elif follow_up_type == FollowUpType.CONFIRM:
                return await self._handle_confirm()
            
            else:
                # NEW_SEARCH 或 REFINE: 执行完整搜索
                return await self._handle_new_search(parse_result)
            
        except Exception as e:
            logger.exception("处理请求时发生错误")
            return XHSFoodResponse(
                status="error",
                error_message=str(e),
            )
    
    async def _handle_filter(self, parse_result: IntentParseResult) -> XHSFoodResponse:
        """处理过滤类追问."""
        target = parse_result.filter_target
        
        if target:
            self._context.exclude_shop(target)
            logger.info(f"  过滤店铺: {target}")
        
        # 过滤上一轮结果
        filtered_recommendations = []
        for name, rec_dict in self._context.last_recommendations.items():
            # 检查是否被排除
            is_excluded = any(
                ex in name or name in ex
                for ex in self._context.excluded_shops
            )
            if not is_excluded:
                filtered_recommendations.append(rec_dict)
        
        self._context.turn_count += 1
        
        return XHSFoodResponse(
            status="ok",
            recommendations=[
                self._dict_to_recommendation(r) for r in filtered_recommendations
            ],
            filtered_count=len(self._context.last_recommendations) - len(filtered_recommendations),
            summary=f"已排除 {target}，剩余 {len(filtered_recommendations)} 家推荐",
        )
    
    async def _handle_expand(self, parse_result: IntentParseResult) -> XHSFoodResponse:
        """处理扩展类追问（多找几家）."""
        intent = parse_result.intent
        
        if not intent and self._context.last_intent:
            intent = FoodSearchIntent.from_dict(self._context.last_intent)
        
        if not intent:
            return XHSFoodResponse(
                status="error",
                error_message="无法扩展搜索，请先进行搜索",
            )
        
        # 执行额外搜索
        logger.info("[Expand] 执行扩展搜索...")
        
        # 重置缓存但保留上下文
        self._shop_mentions = {}
        self._analyzed_shops = {}
        
        # 使用不同的关键词组合
        all_notes = await self._execute_expand_search(intent)
        
        if not all_notes:
            return XHSFoodResponse(
                status="ok",
                recommendations=[
                    self._dict_to_recommendation(r)
                    for r in self._context.last_recommendations.values()
                ],
                summary="未找到更多店铺",
            )
        
        # 分析新笔记
        all_restaurants: List[RestaurantRecommendation] = []
        for note in all_notes:
            analyze_result = await self._analyze_note(note, intent)
            if analyze_result.success:
                all_restaurants.extend(analyze_result.restaurants)
        
        # 合并并过滤
        merged = self._merge_and_validate(all_restaurants)
        
        # 排除已经推荐过的
        new_recommendations = []
        for r in merged:
            if r.is_recommended and r.name not in self._context.last_recommendations:
                new_recommendations.append(r)
        
        # 更新上下文
        self._context.add_recommendations(new_recommendations)
        self._context.turn_count += 1
        
        # 合并旧结果
        all_recommendations = [
            self._dict_to_recommendation(r)
            for r in self._context.last_recommendations.values()
        ]
        
        return XHSFoodResponse(
            status="ok",
            recommendations=all_recommendations,
            summary=f"找到 {len(new_recommendations)} 家新店铺，共 {len(all_recommendations)} 家",
        )
    
    async def _handle_detail(self, parse_result: IntentParseResult) -> XHSFoodResponse:
        """处理详情类追问."""
        target = parse_result.detail_target
        
        if not target:
            return XHSFoodResponse(
                status="error",
                error_message="请指定要查询的店铺名称",
            )
        
        # 从上下文查找
        shop_info = self._context.get_shop_by_name(target)
        
        if shop_info:
            self._context.turn_count += 1
            
            # 构建详情响应
            features = shop_info.get("features", [])
            location = shop_info.get("location", "位置信息见评论区")
            
            detail_summary = f"**{shop_info.get('name', target)}**\n"
            detail_summary += f"- 位置: {location}\n"
            detail_summary += f"- 特点: {', '.join(features[:5])}\n"
            
            if shop_info.get("wanghong_analysis"):
                wa = shop_info["wanghong_analysis"]
                detail_summary += f"- 判定: {wa.get('score', 'unknown')}\n"
                detail_summary += f"- 理由: {', '.join(wa.get('reasons', [])[:3])}\n"
            
            return XHSFoodResponse(
                status="ok",
                recommendations=[self._dict_to_recommendation(shop_info)],
                summary=detail_summary,
            )
        else:
            return XHSFoodResponse(
                status="ok",
                recommendations=[],
                summary=f"未找到 {target} 的信息，可能需要重新搜索",
            )
    
    async def _handle_confirm(self) -> XHSFoodResponse:
        """处理确认类追问（帮我选一家）."""
        if not self._context.last_recommendations:
            return XHSFoodResponse(
                status="error",
                error_message="没有可选的店铺，请先进行搜索",
            )
        
        # 选择评分最高的
        best_shop = None
        best_score = -1
        
        for name, rec_dict in self._context.last_recommendations.items():
            wa = rec_dict.get("wanghong_analysis", {})
            score_str = wa.get("score", "unknown")
            
            # 计算分数
            score_map = {
                "definitely_local": 5,
                "likely_local": 4,
                "unknown": 2,
                "likely_wanghong": 1,
                "definitely_wanghong": 0,
            }
            score = score_map.get(score_str, 2)
            
            # 结合置信度
            confidence = rec_dict.get("confidence", 0.5)
            total = score * confidence
            
            if total > best_score:
                best_score = total
                best_shop = rec_dict
        
        if best_shop:
            self._context.turn_count += 1
            return XHSFoodResponse(
                status="ok",
                recommendations=[self._dict_to_recommendation(best_shop)],
                summary=f"推荐你去 **{best_shop.get('name')}**！",
            )
        
        return XHSFoodResponse(
            status="error",
            error_message="无法选择店铺",
        )
    
    async def _handle_new_search(self, parse_result: IntentParseResult) -> XHSFoodResponse:
        """处理新搜索或细化搜索."""
        intent = parse_result.intent
        
        if not intent:
            return XHSFoodResponse(
                status="error",
                error_message="无法解析搜索意图",
            )
        
        # 重置缓存
        self._shop_mentions = {}
        self._analyzed_shops = {}
        
        # 如果是新搜索，重置上下文（但保留排除列表用于细化）
        if parse_result.follow_up_type == FollowUpType.NEW_SEARCH:
            self._context = ConversationContext()
        
        logger.info(f"  解析结果: {intent.location} / {intent.food_type}")
        
        # Step 2: 执行4阶段搜索
        logger.info("[Step 2] 执行4阶段搜索策略...")
        all_notes = await self._execute_4_stage_search(intent)
        
        if not all_notes:
            return XHSFoodResponse(
                status="ok",
                recommendations=[],
                summary=f"未找到关于 {intent.location} 的相关笔记",
            )
        
        logger.info(f"  共获取 {len(all_notes)} 篇笔记")
        
        # Step 3: 分析每篇笔记
        logger.info("[Step 3] 分析笔记内容和评论...")
        all_restaurants: List[RestaurantRecommendation] = []
        
        for note in all_notes:
            analyze_result = await self._analyze_note(note, intent)
            if analyze_result.success:
                all_restaurants.extend(analyze_result.restaurants)
        
        logger.info(f"  识别出 {len(all_restaurants)} 家店铺")
        
        # Step 4: 交叉验证和合并
        logger.info("[Step 4] 交叉验证和合并店铺信息...")
        merged_restaurants = self._merge_and_validate(all_restaurants)
        
        # Step 5: 过滤网红店 + 用户排除的店
        logger.info("[Step 5] 过滤网红店...")
        recommended = []
        filtered_count = 0
        
        for r in merged_restaurants:
            # 检查是否被用户排除
            is_excluded = any(
                ex in r.name or r.name in ex
                for ex in self._context.excluded_shops
            )
            
            if r.is_recommended and not is_excluded:
                recommended.append(r)
            else:
                filtered_count += 1
        
        # 排序
        recommended.sort(
            key=lambda x: (x.confidence, len(x.source_notes)),
            reverse=True
        )
        
        logger.info(f"  推荐 {len(recommended)} 家，过滤 {filtered_count} 家")
        
        # 更新上下文
        self._context.last_intent = intent.to_dict()
        self._context.add_recommendations(recommended)
        self._context.last_notes = all_notes
        self._context.turn_count += 1
        
        return XHSFoodResponse(
            status="ok",
            recommendations=recommended,
            filtered_count=filtered_count,
            summary=f"在 {intent.location} 找到 {len(recommended)} 家推荐店铺，过滤了 {filtered_count} 家网红店",
        )
    
    async def _execute_expand_search(self, intent: FoodSearchIntent) -> List[Dict[str, Any]]:
        """执行扩展搜索（使用不同关键词）."""
        all_notes = []
        seen_ids: Set[str] = set()
        
        # 排除已搜索过的笔记
        for note in self._context.last_notes:
            note_id = note.get("id") or note.get("note_id", "")
            if note_id:
                seen_ids.add(note_id)
        
        search_tool = self._xhs_registry.get_required("xhs_search")
        
        # 使用不同的关键词
        expand_keywords = [
            f"{intent.location} 隐藏美食",
            f"{intent.location} 老字号",
            f"{intent.location} 街边小店",
        ]
        
        for kw in expand_keywords:
            notes = await self._search_with_keyword(search_tool, kw, seen_ids)
            all_notes.extend(notes)
        
        return all_notes
    
    def _dict_to_recommendation(self, d: Dict[str, Any]) -> RestaurantRecommendation:
        """将字典转换为 RestaurantRecommendation."""
        wa_dict = d.get("wanghong_analysis")
        wanghong = None
        if wa_dict:
            try:
                score = WanghongScore(wa_dict.get("score", "unknown"))
            except ValueError:
                score = WanghongScore.UNKNOWN
            wanghong = WanghongAnalysis(
                score=score,
                confidence=wa_dict.get("confidence", 0.5),
                reasons=wa_dict.get("reasons", []),
            )
        
        return RestaurantRecommendation(
            name=d.get("name", "未知"),
            location=d.get("location"),
            features=d.get("features", []),
            source_notes=d.get("source_notes", []),
            confidence=d.get("confidence", 0.5),
            wanghong_analysis=wanghong,
            is_recommended=d.get("is_recommended", True),
            filter_reason=d.get("filter_reason"),
        )
    
    # ============= 以下是原有的搜索方法（保持不变） =============
    
    async def _execute_4_stage_search(
        self,
        intent: FoodSearchIntent,
    ) -> List[Dict[str, Any]]:
        """执行4阶段搜索策略."""
        all_notes = []
        seen_ids: Set[str] = set()
        
        search_tool = self._xhs_registry.get_required("xhs_search")
        
        # 阶段1: 广撒网
        logger.info("  [Phase 1] 广撒网 - 建立候选池")
        phase1_keywords = self._generate_phase1_keywords(intent)
        for kw in phase1_keywords[:3]:
            notes = await self._search_with_keyword(search_tool, kw, seen_ids)
            all_notes.extend(notes)
        
        # 阶段2: 挖隐藏
        logger.info("  [Phase 2] 挖隐藏 - 发现宝藏店铺")
        phase2_keywords = self._generate_phase2_keywords(intent)
        for kw in phase2_keywords[:3]:
            notes = await self._search_with_keyword(search_tool, kw, seen_ids)
            all_notes.extend(notes)
        
        # 阶段3: 定向验证
        shop_names = self._extract_shop_names(all_notes)
        if shop_names:
            logger.info(f"  [Phase 3] 定向验证 - 验证 {len(shop_names)} 家店铺")
            for i in range(0, min(len(shop_names), 4), 2):
                names = shop_names[i:i+2]
                kw = f"{intent.location} {' '.join(names)}"
                notes = await self._search_with_keyword(search_tool, kw, seen_ids)
                all_notes.extend(notes)
        
        # 阶段4: 细分搜索
        if intent.food_type and intent.food_type != "美食":
            logger.info(f"  [Phase 4] 细分搜索 - {intent.food_type}")
            phase4_keywords = [
                f"{intent.location} {intent.food_type} 老店",
                f"{intent.location} {intent.food_type} 本地人",
            ]
            for kw in phase4_keywords:
                notes = await self._search_with_keyword(search_tool, kw, seen_ids)
                all_notes.extend(notes)
        
        return all_notes
    
    async def _search_with_keyword(
        self,
        search_tool,
        keyword: str,
        seen_ids: Set[str],
    ) -> List[Dict[str, Any]]:
        """执行单次搜索."""
        try:
            result = await search_tool.execute(
                keyword=keyword,
                count=4,
                sort_type="most_comments",
                include_details=True,
                include_comments=True,
            )
            
            if not result.success:
                logger.warning(f"搜索失败: {keyword} - {result.error_message}")
                return []
            
            notes = result.data.get("notes", [])
            new_notes = []
            
            for note in notes:
                note_id = note.get("id") or note.get("note_id", "")
                if note_id and note_id not in seen_ids:
                    seen_ids.add(note_id)
                    new_notes.append(note)
            
            logger.info(f"    搜索 '{keyword}': 新增 {len(new_notes)} 篇")
            return new_notes
            
        except Exception as e:
            logger.warning(f"搜索异常: {keyword} - {e}")
            return []
    
    def _generate_phase1_keywords(self, intent: FoodSearchIntent) -> List[str]:
        """生成阶段1关键词（广撒网）."""
        base = intent.location
        food = intent.food_type or "美食"
        
        keywords = [
            f"{base} 本地人 老店",
            f"{base} {food} 地道",
            f"{base} 本地人 推荐",
        ]
        
        for req in intent.requirements[:2]:
            keywords.append(f"{base} {req}")
        
        return keywords
    
    def _generate_phase2_keywords(self, intent: FoodSearchIntent) -> List[str]:
        """生成阶段2关键词（挖隐藏）."""
        base = intent.location
        
        return [
            f"{base} 苍蝇馆子 好吃",
            f"{base} 小馆子 本地人",
            f"{base} 巷子里 老店",
            f"{base} 不起眼 好吃",
        ]
    
    def _extract_shop_names(self, notes: List[Dict[str, Any]]) -> List[str]:
        """从笔记中提取店铺名."""
        names = []
        for note in notes:
            title = note.get("title") or ""
            if not title:
                continue
            if "店" in title or "馆" in title:
                words = title.replace("｜", " ").replace("|", " ").split()
                for w in words:
                    if ("店" in w or "馆" in w) and 2 <= len(w) <= 10:
                        if w not in names:
                            names.append(w)
        return names[:6]
    
    async def _analyze_note(
        self,
        note: Dict[str, Any],
        intent: FoodSearchIntent,
    ) -> AnalyzeResult:
        """分析单篇笔记."""
        title = note.get("title") or ""
        content = note.get("desc", "") or note.get("full_desc", "")
        note_id = note.get("id") or note.get("note_id", "")
        
        comments = []
        raw_comments = note.get("top_comments", [])
        for c in raw_comments:
            if isinstance(c, dict):
                text = c.get("content", "") or c.get("text", "")
                likes = c.get("like_count", 0) or c.get("likes", 0)
                comments.append(f"{text} [{likes}赞]")
            elif isinstance(c, str):
                comments.append(c)
        
        return await self._analyzer.analyze(
            title=title,
            content=content,
            comments=comments,
            exclude_keywords=intent.exclude_keywords,
            note_id=note_id,
        )
    
    def _merge_and_validate(
        self,
        restaurants: List[RestaurantRecommendation],
    ) -> List[RestaurantRecommendation]:
        """合并相同店铺并进行交叉验证."""
        merged: Dict[str, RestaurantRecommendation] = {}
        
        for r in restaurants:
            name = r.name.strip()
            if not name or name == "未知":
                continue
            
            norm_name = name.replace(" ", "").replace("　", "")
            
            if norm_name in merged:
                existing = merged[norm_name]
                existing.source_notes.extend(r.source_notes)
                existing.features.extend([f for f in r.features if f not in existing.features])
                
                if r.confidence > existing.confidence:
                    existing.confidence = r.confidence
                    existing.wanghong_analysis = r.wanghong_analysis
            else:
                merged[norm_name] = r
        
        for name, r in merged.items():
            source_count = len(set(r.source_notes))
            
            if r.wanghong_analysis:
                score = r.wanghong_analysis.score
                
                if score in (WanghongScore.DEFINITELY_WANGHONG, WanghongScore.LIKELY_WANGHONG):
                    r.is_recommended = False
                    r.filter_reason = f"判定为网红店: {', '.join(r.wanghong_analysis.reasons[:2])}"
                
                elif source_count < 2:
                    r.confidence *= 0.7
                
                elif source_count >= 3 and r.wanghong_analysis.has_local_mentions:
                    r.confidence = min(r.confidence * 1.2, 1.0)
        
        return list(merged.values())
