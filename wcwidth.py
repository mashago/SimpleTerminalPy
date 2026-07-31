"""SimpleTerminalPy — 字符宽度判断（基于 Unicode East Asian Width）。

C 版 SimpleTerminal 没有这个文件 — 它只支持 ASCII（全为 1 列宽）。
Python 版要支持中文/日韩文等双列字符，必须区分 1 列和 2 列。
"""

import unicodedata


def char_width(ch: str) -> int:
    """返回字符在等宽终端中的列宽。

    规则（兼容 wcwidth）：
    - 控制字符 (C0/C1) 和 NULL：0
    - CJK 全角/宽字符 (East Asian Width F/W)：2
    - 其余：1
    """
    if not ch:
        return 0

    cp = ord(ch)

    # NULL
    if cp == 0:
        return 0

    # C0 控制字符 (0x00-0x1F) + DEL (0x7F)
    if cp < 0x20 or cp == 0x7F:
        return 0

    # C1 控制字符 (0x80-0x9F)
    if 0x80 <= cp <= 0x9F:
        return 0

    # 组合字符 (0x0300-0x036F 等) — 零宽度
    cat = unicodedata.category(ch)
    if cat in ('Mn', 'Me', 'Cf'):
        return 0

    # East Asian Width
    ea = unicodedata.east_asian_width(ch)
    if ea in ('F', 'W'):   # Fullwidth, Wide
        return 2

    return 1
