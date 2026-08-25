#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 release_notes.md。

由 CI 调用。写成 Python 而不是内嵌 PowerShell here-string —— 中文 + 反引号 +
`$` 在 pwsh 里混一起太容易踩转义坑，且不好本地验证。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import version as appver  # noqa: E402

SUMS = ROOT / "artifacts" / "SHA256SUMS.txt"
OUT = ROOT / "release_notes.md"

TEMPLATE = """## OutlookRegister v{v}

Windows 绿色便携版，解压即用，无需安装 Python 或浏览器。

### 下载说明

- **全新安装** 下载 `OutlookRegister-v{v}-full.zip`（含内置 Chromium）
- **从旧版更新** 在程序内「关于与更新」里点检查更新，或手动下载 `-patch.zip` 覆盖

### 使用方法

1. 解压到有写权限的目录（**不要放在 C:\\Program Files**）
2. 双击 `OutlookRegister.exe`
3. 浏览器会自动打开控制台，首次访问需创建管理员账号
4. 在「系统设置」里填写代理等参数后即可开始注册

控制台仅监听 `127.0.0.1`，其他设备无法访问。

### 升级不会丢数据

`config.json`、`admin.json`、`Results/`、`log/` 在更新时会被保留。

### SHA256

```
{sums}
```
"""


def main():
    sums = SUMS.read_text(encoding="utf-8").strip() if SUMS.is_file() else "(未生成)"
    notes = TEMPLATE.format(v=appver.VERSION, sums=sums)
    OUT.write_text(notes, encoding="utf-8")
    print(notes)


if __name__ == "__main__":
    main()
