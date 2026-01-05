import json
import math
import random
import os
import sys
import subprocess
import shutil
import tempfile

from .cookie_util import trans_cookies

# Compute base path for static files
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.abspath(os.path.join(_CURRENT_DIR, '..', 'static'))

def get_static_file(filename):
    return os.path.join(STATIC_DIR, filename)

# ========== Node.js Path Setup ==========
NODE_PATHS = [
    'E:/nodejs',
    'E:\\nodejs', 
    'C:/Program Files/nodejs',
    'C:\\Program Files\\nodejs',
]

# Try to restore PATH from registry if corrupted
current_path = os.environ.get('PATH', '')
if '%PATH%' in current_path or not current_path:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment') as key:
            system_path, _ = winreg.QueryValueEx(key, 'Path')
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Environment') as key:
            try:
                user_path, _ = winreg.QueryValueEx(key, 'Path')
            except:
                user_path = ''
        os.environ['PATH'] = system_path + os.pathsep + user_path
    except:
        pass

# Add Node.js paths
for node_path in NODE_PATHS:
    if os.path.exists(node_path) and node_path not in os.environ.get('PATH', ''):
        os.environ['PATH'] = node_path + os.pathsep + os.environ.get('PATH', '')

# Find node executable
NODE_EXE = shutil.which('node')
if not NODE_EXE:
    # Try direct paths
    for p in NODE_PATHS:
        candidate = os.path.join(p, 'node.exe')
        if os.path.exists(candidate):
            NODE_EXE = candidate
            break

if NODE_EXE:
    print(f"INFO: Using Node.js at {NODE_EXE}", file=sys.stderr)
else:
    raise RuntimeError("Node.js not found. Please install Node.js and ensure it's in PATH.")

# ========== Custom JS Executor (bypasses PyExecJS) ==========
class NodeJSExecutor:
    """Execute JavaScript using Node.js subprocess directly."""
    
    def __init__(self, js_source: str):
        self.js_source = js_source
        
    def call(self, func_name: str, *args):
        """Call a JavaScript function with arguments."""
        # Build the call expression
        args_json = json.dumps(args, ensure_ascii=False)
        
        # Create a wrapper script that executes the function
        # Use a unique marker to identify our output
        marker = "__EXECJS_RESULT__"
        wrapper = f"""
{self.js_source}

try {{
    var result = {func_name}.apply(null, {args_json});
    console.log("{marker}" + JSON.stringify({{"ok": true, "result": result}}));
}} catch(e) {{
    console.log("{marker}" + JSON.stringify({{"ok": false, "error": e.message}}));
}}
"""
        # Write to temp file and execute
        with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8') as f:
            f.write(wrapper)
            temp_path = f.name
        
        try:
            result = subprocess.run(
                [NODE_EXE, temp_path],
                capture_output=True,
                text=True,
                encoding='utf-8',
                timeout=30
            )
            
            if result.returncode != 0:
                raise RuntimeError(f"Node.js error: {result.stderr}")
            
            output = result.stdout.strip()
            if not output:
                raise RuntimeError(f"Empty output from Node.js. stderr: {result.stderr}")
            
            # Find the line with our marker
            json_line = None
            for line in output.split('\n'):
                if marker in line:
                    json_line = line.replace(marker, '')
                    break
            
            if not json_line:
                raise RuntimeError(f"Could not find result in output: {output[:500]}")
            
            data = json.loads(json_line)
            if data.get('ok'):
                return data.get('result')
            else:
                raise RuntimeError(f"JS error: {data.get('error')}")
        finally:
            try:
                os.unlink(temp_path)
            except:
                pass

# ========== Load JS Files ==========
def sanitize_js(content: str) -> str:
    """Escape non-ASCII for Windows compatibility."""
    result = []
    for char in content:
        if ord(char) > 127:
            result.append(f'\\u{ord(char):04x}')
        else:
            result.append(char)
    return ''.join(result)

# Load main JS
js_file_path = get_static_file('xhs_xs_xsc_56.js')
if not os.path.exists(js_file_path):
    raise FileNotFoundError(f"Static JS file not found: {js_file_path}")

with open(js_file_path, 'r', encoding='utf-8') as f:
    js_content = sanitize_js(f.read())

js = NodeJSExecutor(js_content)

# Load XRAY JS with packs combined
def load_combined_xray_js():
    main_js_path = get_static_file('xhs_xray.js')
    pack1_path = get_static_file('xhs_xray_pack1.js')
    pack2_path = get_static_file('xhs_xray_pack2.js')

    if not os.path.exists(main_js_path):
        raise FileNotFoundError(f"Missing {main_js_path}")
    
    with open(main_js_path, 'r', encoding='utf-8') as f:
        main_content = f.read()

    split_marker = "//# sourceMappingURL="
    usage_marker = "var n = zc666(36497)"
    
    if split_marker in main_content and usage_marker in main_content:
        part1 = main_content.split(split_marker)[0]
        part2 = main_content.split(usage_marker)[1]
        
        with open(pack1_path, 'r', encoding='utf-8') as f:
            pack1 = f.read()
        with open(pack2_path, 'r', encoding='utf-8') as f:
            pack2 = f.read()
            
        combined = part1 + "\n" + pack1 + "\n" + pack2 + "\n" + usage_marker + part2
        return sanitize_js(combined)
    
    raise ValueError("Could not parse xhs_xray.js structure")

xray_js = NodeJSExecutor(load_combined_xray_js())

# ========== Utility Functions ==========
def generate_x_b3_traceid(length=16):
    chars = "abcdef0123456789"
    return ''.join(chars[math.floor(16 * random.random())] for _ in range(length))

def generate_xs_xs_common(a1, api, data='', method='POST'):
    ret = js.call('get_request_headers_params', api, data, a1, method)
    return ret['xs'], ret['xt'], ret['xs_common']

def generate_xs(a1, api, data=''):
    ret = js.call('get_xs', api, data, a1)
    return ret['X-s'], ret['X-t']

def generate_xray_traceid():
    return xray_js.call('traceId')

def get_common_headers():
    return {
        "authority": "www.xiaohongshu.com",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept-language": "zh-CN,zh;q=0.9",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "referer": "https://www.xiaohongshu.com/",
        "sec-ch-ua": "\"Chromium\";v=\"122\", \"Not(A:Brand\";v=\"24\", \"Google Chrome\";v=\"122\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"Windows\"",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "same-origin",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }

def get_request_headers_template():
    return {
        "authority": "edith.xiaohongshu.com",
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "cache-control": "no-cache",
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://www.xiaohongshu.com",
        "pragma": "no-cache",
        "referer": "https://www.xiaohongshu.com/",
        "sec-ch-ua": "\"Not A(Brand\";v=\"99\", \"Microsoft Edge\";v=\"121\", \"Chromium\";v=\"121\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"Windows\"",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
        "x-b3-traceid": "",
        "x-mns": "unload",
        "x-s": "",
        "x-s-common": "",
        "x-t": "",
        "x-xray-traceid": generate_xray_traceid()
    }

def generate_headers(a1, api, data='', method='POST'):
    xs, xt, xs_common = generate_xs_xs_common(a1, api, data, method)
    x_b3_traceid = generate_x_b3_traceid()
    headers = get_request_headers_template()
    headers['x-s'] = xs
    headers['x-t'] = str(xt)
    headers['x-s-common'] = xs_common
    headers['x-b3-traceid'] = x_b3_traceid
    if data:
        data = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
    return headers, data

def generate_request_params(cookies_str, api, data='', method='POST'):
    cookies = trans_cookies(cookies_str)
    a1 = cookies['a1']
    headers, data = generate_headers(a1, api, data, method)
    return headers, cookies, data

def splice_str(api, params):
    url = api + '?'
    for key, value in params.items():
        if value is None:
            value = ''
        url += key + '=' + str(value) + '&'
    return url[:-1]
