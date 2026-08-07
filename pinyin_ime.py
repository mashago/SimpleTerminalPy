"""pinyin_ime.py — OSK 拼音输入法核心逻辑（纯逻辑，无 SDL 依赖）。

字典 pinyin_dict.json 由 generate_pinyin_dict.py 生成
（pypinyin 拼音表 + Jun Da 字频表），格式:
  {"zhong": [["中", 频率], ["种", 频率], ...], ...}
每个拼音的候选已按频率降序。

用法:
  ime = PinyinIME()
  chars, total = ime.page("zhong", 0)   # 第 0 页候选 + 总页数
"""

import json
import os

PAGE_SIZE = 9
_DICT_FILENAME = "pinyin_dict.json"


class PinyinIME:
    """拼音候选查询：前缀匹配 + 频率排序 + 分页。"""

    def __init__(self, dict_path: str | None = None):
        # 默认路径与字体一致：程序所在目录
        self.dict_path = dict_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), _DICT_FILENAME)
        self._table: dict[str, list] | None = None

    @property
    def loaded(self) -> bool:
        return self._table is not None

    def load(self) -> bool:
        """加载字典（懒加载入口；失败返回 False 并保留未加载状态）。"""
        try:
            with open(self.dict_path, encoding="utf-8") as f:
                self._table = json.load(f)
            return True
        except (OSError, json.JSONDecodeError):
            return False

    def candidates(self, pinyin: str) -> list[str]:
        """返回该拼音串（前缀匹配）的全部候选，按频率降序。

        组合区每输入一个字母调用一次：候选 = 所有以该串开头的
        拼音（如 "zh" → 中/只/之/重/种...）合并后按频率排序。
        无匹配返回空列表。
        """
        if not self._table and not self.load():
            return []
        pinyin = pinyin.strip().lower()
        if not pinyin:
            return []

        merged: dict[str, int] = {}   # char → freq（多音字去重，取最高频）
        for key, entries in self._table.items():
            if not key.startswith(pinyin):
                continue
            for ch, freq in entries:
                if freq > merged.get(ch, -1):
                    merged[ch] = freq
        return [ch for ch, _ in
                sorted(merged.items(), key=lambda kv: (-kv[1], kv[0]))]

    def page(self, pinyin: str, page: int = 0) -> tuple[list[str], int]:
        """返回第 page 页（0 起）候选与总页数。

        page 越界时自动夹取到 [0, total-1]。
        """
        cands = self.candidates(pinyin)
        total = (len(cands) + PAGE_SIZE - 1) // PAGE_SIZE
        if page < 0:
            page = 0
        elif page >= total:
            page = max(0, total - 1)
        start = page * PAGE_SIZE
        return cands[start:start + PAGE_SIZE], total
