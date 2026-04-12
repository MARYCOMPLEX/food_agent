# encoding: utf-8
import urllib
import requests
from xhs_food.spider.xhs_utils.xhs_util import splice_str, generate_request_params


class CommentsMixin:
    """笔记评论相关API"""

    def get_note_out_comment(self, note_id: str, cursor: str, xsec_token: str, cookies_str: str, proxies: dict = None):
        """
            获取指定位置的笔记一级评论
            :param note_id 笔记的id
            :param cursor 指定位置的评论的cursor
            :param cookies_str 你的cookies
            返回指定位置的笔记一级评论
        """
        res_json = None
        try:
            api = "/api/sns/web/v2/comment/page"
            params = {
                "note_id": note_id,
                "cursor": cursor,
                "top_comment_id": "",
                "image_formats": "jpg,webp,avif",
                "xsec_token": xsec_token
            }
            splice_api = splice_str(api, params)
            headers, cookies, data = generate_request_params(cookies_str, splice_api, '', 'GET')
            response = requests.get(self.base_url + splice_api, headers=headers, cookies=cookies, proxies=proxies)
            res_json = response.json()
            success, msg = res_json["success"], res_json["msg"]
        except Exception as e:
            success = False
            msg = str(e)
        return success, msg, res_json

    def get_note_all_out_comment(self, note_id: str, xsec_token: str, cookies_str: str, proxies: dict = None):
        """
            获取笔记的全部一级评论
            :param note_id 笔记的id
            :param cookies_str 你的cookies
            返回笔记的全部一级评论
        """
        cursor = ''
        note_out_comment_list = []
        try:
            while True:
                success, msg, res_json = self.get_note_out_comment(note_id, cursor, xsec_token, cookies_str, proxies)
                if not success:
                    raise Exception(msg)
                # Safely access nested data
                data = res_json.get("data", {})
                if not data:
                    break
                comments = data.get("comments", [])
                if 'cursor' in data:
                    cursor = str(data["cursor"])
                else:
                    break
                note_out_comment_list.extend(comments)
                if len(note_out_comment_list) == 0 or not data.get("has_more", False):
                    break
        except Exception as e:
            success = False
            msg = str(e)
        return success, msg, note_out_comment_list

    def get_note_inner_comment(self, comment: dict, cursor: str, xsec_token: str, cookies_str: str, proxies: dict = None):
        """
            获取指定位置的笔记二级评论
            :param comment 笔记的一级评论
            :param cursor 指定位置的评论的cursor
            :param cookies_str 你的cookies
            返回指定位置的笔记二级评论
        """
        res_json = None
        try:
            api = "/api/sns/web/v2/comment/sub/page"
            params = {
                "note_id": comment['note_id'],
                "root_comment_id": comment['id'],
                "num": "10",
                "cursor": cursor,
                "image_formats": "jpg,webp,avif",
                "top_comment_id": '',
                "xsec_token": xsec_token
            }
            splice_api = splice_str(api, params)
            headers, cookies, data = generate_request_params(cookies_str, splice_api, '', 'GET')
            response = requests.get(self.base_url + splice_api, headers=headers, cookies=cookies, proxies=proxies)
            res_json = response.json()
            success, msg = res_json["success"], res_json["msg"]
        except Exception as e:
            success = False
            msg = str(e)
        return success, msg, res_json

    def get_note_all_inner_comment(self, comment: dict, xsec_token: str, cookies_str: str, proxies: dict = None):
        """
            获取笔记的全部二级评论
            :param comment 笔记的一级评论
            :param cookies_str 你的cookies
            返回笔记的全部二级评论
        """
        try:
            if not comment.get('sub_comment_has_more', False):
                return True, 'success', comment
            cursor = comment.get('sub_comment_cursor', '')
            inner_comment_list = []
            while True:
                success, msg, res_json = self.get_note_inner_comment(comment, cursor, xsec_token, cookies_str, proxies)
                if not success:
                    raise Exception(msg)
                # Safely access nested data
                data = res_json.get("data", {})
                if not data:
                    break
                comments = data.get("comments", [])
                if 'cursor' in data:
                    cursor = str(data["cursor"])
                else:
                    break
                inner_comment_list.extend(comments)
                if not data.get("has_more", False):
                    break
            if 'sub_comments' not in comment:
                comment['sub_comments'] = []
            comment['sub_comments'].extend(inner_comment_list)
        except Exception as e:
            success = False
            msg = str(e)
        return success, msg, comment

    def get_note_all_comment(self, url: str, cookies_str: str, proxies: dict = None):
        """
            获取一篇文章的所有评论
            :param note_id: 你想要获取的笔记的id
            :param cookies_str: 你的cookies
            返回一篇文章的所有评论
        """
        out_comment_list = []
        try:
            urlParse = urllib.parse.urlparse(url)
            note_id = urlParse.path.split("/")[-1]

            # Safely parse query parameters
            kvDist = {}
            if urlParse.query:
                for kv in urlParse.query.split('&'):
                    if '=' in kv:
                        key, value = kv.split('=', 1)
                        kvDist[key] = value

            xsec_token = kvDist.get('xsec_token', '')
            success, msg, out_comment_list = self.get_note_all_out_comment(note_id, xsec_token, cookies_str, proxies)
            if not success:
                raise Exception(msg)
            for comment in out_comment_list:
                success, msg, new_comment = self.get_note_all_inner_comment(comment, xsec_token, cookies_str, proxies)
                if not success:
                    raise Exception(msg)
        except Exception as e:
            success = False
            msg = str(e)
        return success, msg, out_comment_list
