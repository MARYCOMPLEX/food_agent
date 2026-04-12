# encoding: utf-8
"""
    获小红书的api
    :param cookies_str: 你的cookies
"""
from .xhs_base import XHS_ApisBase
from .xhs_feed_user import FeedUserMixin
from .xhs_user_notes import UserNotesMixin
from .xhs_search_notes import SearchNotesMixin
from .xhs_comments import CommentsMixin
from .xhs_social_media import SocialMediaMixin


class XHS_Apis(XHS_ApisBase, FeedUserMixin, UserNotesMixin, SearchNotesMixin, CommentsMixin, SocialMediaMixin):
    pass
