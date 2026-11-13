import os
import random
import string
import secrets
import threading

import paths

# 姓名库文件：每行一个姓名，如 EdwardRiley
# 只读资源 —— 冻结后在 _internal/app_data/，开发时在项目根
_NAMES_FILE = str(paths.NAMES_FILE)
_names_cache = None
_names_lock = threading.Lock()

# 纯字母前缀长度限制（Outlook 本地部分上限 64，这里留出安全区间）
DEFAULT_PURE_LETTER_LENGTH = 8
MIN_PURE_LETTER_LENGTH = 4
MAX_PURE_LETTER_LENGTH = 32


def normalize_letters_length(value, default=DEFAULT_PURE_LETTER_LENGTH):
    """把配置里的位数转成安全整数：非法值用默认，超出范围夹到 4~32。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(MIN_PURE_LETTER_LENGTH, min(MAX_PURE_LETTER_LENGTH, n))


def _load_names():
    """懒加载姓名列表（线程安全，带缓存）。文件缺失/为空时返回空列表。"""
    global _names_cache
    if _names_cache is not None:
        return _names_cache
    with _names_lock:
        if _names_cache is not None:
            return _names_cache
        try:
            with open(_NAMES_FILE, encoding='utf-8-sig') as f:
                names = [ln.strip() for ln in f if ln.strip()]
            _names_cache = names if names else []
        except Exception:
            _names_cache = []
        return _names_cache


def random_email(length=None, pure_letters=False, letters_length=DEFAULT_PURE_LETTER_LENGTH):
    """随机生成 Outlook 邮箱前缀。

    1) pure_letters=True：开启「纯字母前缀」开关，生成长度为 letters_length 的
       纯小写字母前缀（如 kxjqmwba），位数范围 4~32。
    2) 否则优先：从 english_name_generator.txt 随机选一个姓名 + 5 位随机数字
       （如 edwardriley37284）。
    3) 姓名库文件缺失/为空时回退纯随机字符串（原逻辑）。
    """
    if pure_letters:
        n = normalize_letters_length(letters_length)
        return ''.join(random.choices(string.ascii_lowercase, k=n))

    names = _load_names()
    if names:
        name = random.choice(names)
        digits = ''.join(random.choices(string.digits, k=5))
        return name + digits

    # 回退：默认随机长度 11~17
    if length is None:
        length = random.randint(11, 17)

    first_char = random.choice(string.ascii_lowercase)

    other_chars = []
    for _ in range(length - 1):
        # 数字概率 10%
        if random.random() < 0.1:
            other_chars.append(random.choice(string.digits))
        else:
            other_chars.append(random.choice(string.ascii_lowercase))

    return first_char + ''.join(other_chars)

def generate_strong_password(length=None):
    if length is None:
        length = random.randint(10, 14)

    chars = string.ascii_letters + string.digits + "!@#$%^&*"

    while True:
        password = ''.join(secrets.choice(chars) for _ in range(length))

        if (
            any(c.islower() for c in password)
            and any(c.isupper() for c in password)
            and any(c.isdigit() for c in password)
            and any(c in "!@#$%^&*" for c in password)
        ):
            return password
