#!/usr/bin/env python3
"""生成 pinyin_dict.json — OSK 拼音输入法的静态字典。

用法: python3 generate_pinyin_dict.py [字频表路径] [输出路径]

数据来源:
  - 拼音表: pypinyin（MIT）的单字拼音表（Style.NORMAL，无音调，ü→v）
  - 字频表: Jun Da 现代汉语字频表（chinese_frquency.txt，9933 常用字，
    tab 分隔：序号/汉字/频率/累计%/拼音/英文）。不在表内的生僻字
    频次记 0（排在所有常用字之后）。

输出: {"pinyin": [[char, freq], ...]} — 每个拼音的候选按频次降序。
"""

import json
import sys

from pypinyin import Style, pinyin
from pypinyin.pinyin_dict import pinyin_dict

FREQ_PATH = sys.argv[1] if len(sys.argv) > 1 else \
    "/root/workspace/my_terminal/chinese_frquency.txt"
OUT_PATH = sys.argv[2] if len(sys.argv) > 2 else "pinyin_dict.json"


def load_freq(path: str) -> dict[str, tuple[int, set[str]]]:
    """解析 Jun Da 字频表 → {汉字: (原始频次, 读音集合)}。

    读音列（第 5 列，CEDICT 来源）格式如 "de/di2/di4"——
    去声调数字、ü→v 归一化，用于与 pypinyin 读音做交叉验证，
    剔除 pypinyin 单字表的错误读音（如 而 被标成 er/neng）。
    """
    result: dict[str, tuple[int, set[str]]] = {}
    for line in open(path, encoding="utf-8"):
        cols = line.rstrip("\n").split("\t")
        if len(cols) < 5 or len(cols[1]) != 1 or not cols[2].isdigit():
            continue
        readings: set[str] = set()
        for one in cols[4].split("/"):
            bare = one.rstrip("0123456789").replace("ü", "v")
            if bare:
                readings.add(bare)
        result[cols[1]] = (int(cols[2]), readings)
    return result


def main():
    # 1. 收集全部单字拼音（pypinyin 单字表：codepoint → 带声调的拼音，
    #    逗号分隔多读音）→ 用 Style.NORMAL 转纯字母（líng → ling，
    #    ü → v，如 绿 → lv）；heteronym=True 取多音字全部读音。
    char_pinyins: dict[str, set[str]] = {}
    for cp in pinyin_dict:
        ch = chr(cp)
        readings = pinyin(ch, style=Style.NORMAL, heteronym=True)
        for one in readings[0]:
            if one:
                char_pinyins.setdefault(ch, set()).add(one)

    # 2. 字频（Jun Da 表）+ 读音交叉验证
    #    - 常用字（在表中）：pypinyin 读音 ∩ 字频表读音（剔除错误读音）
    #    - 生僻字（不在表中）：单信 pypinyin；频次 0（排最后）
    freq = load_freq(FREQ_PATH)
    print(f"字频表载入: {len(freq)} 个汉字")

    # 3. 组装候选表：pinyin → [(char, freq), ...]，按频次降序（同频按 Unicode 序）
    table: dict[str, list] = {}
    dropped = 0
    for ch, pys in char_pinyins.items():
        entry = freq.get(ch)
        if entry is not None:
            f, verified = entry
            inter = pys & verified
            if inter:
                pys = inter
            else:
                dropped += 1   # 交集为空（格式差异）— 保留 pypinyin 读音
        else:
            f = 0
        for py in pys:
            table.setdefault(py, []).append((ch, f))
    print(f"读音交集为空退回 pypinyin 的字数: {dropped}")
    for py in table:
        table[py].sort(key=lambda item: (-item[1], item[0]))

    # 4. 写文件
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(table, f, ensure_ascii=False)

    n_char = len(char_pinyins)
    n_py = len(table)
    n_entry = sum(len(v) for v in table.values())
    print(f"汉字数: {n_char}, 拼音数: {n_py}, 候选总条目: {n_entry}")
    for test in ("zhong", "ni", "hao", "shi", "nihao"):
        cands = [c for c, _ in table.get(test, [])[:6]]
        print(f"  {test}: {cands}")


if __name__ == "__main__":
    main()
