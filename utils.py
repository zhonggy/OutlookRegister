import os
import random
import string
import secrets
import threading

# 姓名库文件（与 utils.py 同目录）：每行一个姓名，如 EdwardRiley
_NAMES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'english_name_generator.txt')
_names_cache = None
_names_lock = threading.Lock()


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


def random_email(length=None):
    """随机生成 Outlook 邮箱前缀。

    优先：从 english_name_generator.txt 随机选一个姓名 + 5 位随机数字
    （如 edwardriley37284）。文件缺失/为空时回退纯随机字符串（原逻辑）。
    """
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
