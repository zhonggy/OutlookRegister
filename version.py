"""版本与更新元信息。发版时手动递增 VERSION。"""

VERSION = "1.2"

GITHUB_OWNER = "zhonggy"
GITHUB_REPO = "OutlookRegister"
GITHUB_BRANCH = "bate"

RELEASE_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
RELEASE_PAGE = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"

APP_NAME = "OutlookRegister"
DISPLAY_NAME = f"{APP_NAME} v{VERSION}"


def version_tuple(text: str) -> tuple:
    """"v1.10" -> (1, 10)。用于数值比较，避免字符串比较把 1.10 判成小于 1.9。"""
    s = (text or "").strip().lstrip("vV")
    parts = []
    for chunk in s.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(remote: str, local: str = VERSION) -> bool:
    a, b = version_tuple(remote), version_tuple(local)
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b
