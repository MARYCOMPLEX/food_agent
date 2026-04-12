# encoding: utf-8
import json
import re
import urllib
import requests
from xhs_food.spider.xhs_utils.xhs_util import splice_str, generate_request_params, generate_x_b3_traceid, get_common_headers
from loguru import logger


class XHS_ApisBase:
    """小红书API基类"""
    def __init__(self):
        self.base_url = "https://edith.xiaohongshu.com"
