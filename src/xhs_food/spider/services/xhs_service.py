import json
import random
import time
import re
from typing import List, Dict, Any, Optional, Literal, Union
from loguru import logger

from xhs_food.spider.apis.xhs_pc_apis import XHS_Apis
from xhs_food.spider.xhs_utils.common_util import load_env
from xhs_food.spider.core.logger import request_logger
from xhs_food.spider.core.config import config

class XHSService:
    def __init__(self):
        self.cookies_str = load_env()
        if not self.cookies_str:
            logger.warning("No cookies found in environment variables. Requests may fail.")
        self.api = XHS_Apis()
        
        # Cache for storing xsec_tokens
        self._token_cache: Dict[str, str] = {}

    def _wait_random(self):
        """Sleep for a random interval."""
        s = random.uniform(config.REQUEST_DELAY_MIN, config.REQUEST_DELAY_MAX)
        time.sleep(s)

    def _log(self, tool_name: str, endpoint: str, params: dict, result: tuple):
        success, msg, data = result
        request_logger.log_request(
            tool_name=tool_name,
            endpoint=endpoint,
            params=params,
            response=data if success else {"error": msg},
            success=success,
            error_msg=msg if not success else None
        )

    def _extract_id_and_token(self, url_or_id: str) -> tuple[str, Optional[str]]:
        """Extract ID and optionally token from input."""
        note_id = url_or_id
        token = None
        
        if "xiaohongshu.com" in url_or_id:
            match = re.search(r'/explore/([a-zA-Z0-9]+)', url_or_id)
            if match:
                note_id = match.group(1)
            
            t_match = re.search(r'xsec_token=([^&]+)', url_or_id)
            if t_match:
                token = t_match.group(1)
                
        if not token:
            token = self._token_cache.get(note_id)
            
        return note_id, token

    def _construct_safe_url(self, note_id: str, token: Optional[str] = None) -> str:
        base = f"https://www.xiaohongshu.com/explore/{note_id}"
        if not token:
            token = self._token_cache.get(note_id)
        if token:
            return f"{base}?xsec_token={token}&xsec_source=pc_search"
        return base

    def _simplify_comment(self, comment: Dict) -> Dict:
        """Keep only essential fields for LLM to save tokens."""
        return {
            "content": comment.get("content", ""),
            "user": comment.get("user_info", {}).get("nickname", "Unknown"),
            "likes": comment.get("like_count", 0),
            "date": comment.get("create_time_str", ""),
            "sub_comments_count": comment.get("sub_comment_count", 0),
            # Only include sub-comments if they exist and are simplified
            "sub_comments": [self._simplify_comment(sc) for sc in comment.get("sub_comments", [])] if comment.get("sub_comments") else []
        }

    def search_xhs(
        self, 
        keyword: str, 
        count: int = 4, 
        sort_type: Union[int, str] = 0, 
        note_type: int = 0,
        include_details: bool = True,
        include_comments: bool = False
    ) -> Dict[str, Any]:
        """
        Search with configurable sorting and optimization.
        """
        # Map string sort types to int
        if isinstance(sort_type, str):
            sort_map = {"general": 0, "newest": 1, "popular": 2, "most_comments": 3}
            sort_type_int = sort_map.get(sort_type, 0)
        else:
            sort_type_int = sort_type

        self._wait_random()
        
        # 1. Search
        search_res = self.api.search_some_note(
            query=keyword, 
            require_num=count, 
            cookies_str=self.cookies_str,
            sort_type_choice=sort_type_int,
            note_type=note_type
        )
        self._log("search_xhs", "search_some_note", {"k": keyword, "n": count, "sort": sort_type_int}, search_res)
        
        success, msg, notes_data = search_res
        if not success:
            return {"status": "failed", "message": msg, "notes": []}
            
        processed_notes = []
        for note in notes_data:
            nid = note.get('id')
            token = note.get('xsec_token')
            if nid and token:
                self._token_cache[nid] = token
            
            # Simplified note object
            n_obj = {
                "id": nid,
                "title": note.get('title'),
                "desc": note.get('desc', ''), # Short summary
                "stats": {
                    "likes": note.get('likes'),
                    "comments": note.get('comments'), # Search result usually has valid comment count? Check 'interact_info'
                },
                "link": self._construct_safe_url(nid, token)
            }
            
            # Correctly extract stats
            if 'interact_info' in note:
                 n_obj['stats']['likes'] = note['interact_info'].get('liked_count')
                 n_obj['stats']['comments'] = note['interact_info'].get('comment_count')

            # Fetch details
            if include_details and nid:
                url = n_obj['link']
                d_res = self.api.get_note_info(url, self.cookies_str)
                if d_res[0]:
                    d_data = d_res[1] if isinstance(d_res[1], dict) else d_res[2] # API returns success, msg, data OR success, msg. Wait.
                    # api.get_note_info returns success, msg, res_json. res_json has ["data"]
                    d_data = d_res[2].get("data", {}) if d_res[2] else {}
                    n_obj['full_desc'] = d_data.get('desc', '')
                    n_obj['tags'] = [t['name'] for t in d_data.get('tag_list', [])]
                else:
                    n_obj['detail_error'] = d_res[1]

            # Fetch Comments (Limited)
            if include_comments and nid:
                # Use limited fetch for search results (e.g. top 5)
                comments_data = self._fetch_comments_paginated(nid, max_count=5)
                n_obj['top_comments'] = [self._simplify_comment(c) for c in comments_data]
            
            processed_notes.append(n_obj)
            
        return {
            "status": "success",
            "count": len(processed_notes),
            "notes": processed_notes
        }

    def _fetch_comments_paginated(self, note_id: str, max_count: int = 20) -> List[Dict]:
        """Fetch comments with strict limit using cursor pagination."""
        token = self._token_cache.get(note_id, "")
        cursor = ""
        collected = []
        
        while len(collected) < max_count:
            # Call low-level API directly to control pagination
            res = self.api.get_note_out_comment(note_id, cursor, token, self.cookies_str)
            if not res[0]:
                break
                
            data = res[2].get("data", {})
            if not data: 
                break
                
            comments = data.get("comments", [])
            if not comments:
                break
                
            collected.extend(comments)
            
            if data.get("has_more") and "cursor" in data:
                cursor = data["cursor"]
                self._wait_random() # Polite delay between pages
            else:
                break
                
        return collected[:max_count]

    def get_xhs_note(self, url_or_id: str, include_comments: bool = True, max_comments: int = 20) -> Dict:
        """Get note with controllable comment volume."""
        nid, token = self._extract_id_and_token(url_or_id)
        url = self._construct_safe_url(nid, token)
        
        d_res = self.api.get_note_info(url, self.cookies_str)
        if not d_res[0]:
            return {"status": "error", "message": d_res[1]}
            
        data = d_res[2].get("data", {})
        result = {
            "id": nid,
            "title": data.get("title"),
            "desc": data.get("desc"),
            "time": data.get("time"),
            "user": data.get("user", {}).get("nickname"),
            "stats": data.get("interact_info", {}),
            "status": "success"
        }
        
        if include_comments:
            raw_comments = self._fetch_comments_paginated(nid, max_count=max_comments)
            result['comments'] = [self._simplify_comment(c) for c in raw_comments]
            result['comments_count'] = len(result['comments'])
            
        return result

    def batch_xhs_research(self, topics: List[str], notes_per_topic: int = 4) -> Dict:
        """Batch research with optimized settings."""
        results = {}
        for topic in topics:
            res = self.search_xhs(
                topic, 
                count=notes_per_topic, 
                sort_type="most_comments", # Default to most comments for research
                include_details=True,
                include_comments=True # Will fetch top 5 simplified
            )
            results[topic] = res.get("notes", [])
        return {"status": "success", "results": results}

