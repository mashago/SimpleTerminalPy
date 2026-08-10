"""pinyin_ime.py — 拼音输入法核心（字典查询引擎 + 组合状态机）。

字典 pinyin_dict.json 由 generate_pinyin_dict.py 生成
（pypinyin 拼音表 + Jun Da 字频表），格式:
  {"zhong": [["中", 频率], ["种", 频率], ...], ...}
每个拼音的候选已按频率降序。

两个类：
  PinyinEngine  字典查询引擎（前缀匹配/排序/分页/懒加载）——最内层，
                多个输入法可共享一个实例（字典只加载一次）。
  PinyinIME     组合状态机（组合区/页码/按键路由）——纯逻辑，
                无渲染无按键语义，供 OSK 拼音键盘与外接键盘拼音复用。

用法:
  ime = PinyinIME(PinyinEngine("pinyin_dict.json"))
  out = ime.process("z")      # 字母进组合，返回 None
  out = ime.process("1")      # 选中候选，返回汉字
"""

import json
import os

PAGE_SIZE = 9

# 精确优先只对"常用音节"生效：音节的最高频字达到该阈值才精确优先。
# 叹词/生僻音节（唔/嗯/哦，最高频字 <1 万）不精确优先，
# 否则打 n 时"唔"会跳队到 你/能 之前。
EXACT_MIN_FREQ = 10000


class PinyinEngine:
    """字典查询引擎：前缀匹配 + 精确优先 + 频率排序 + 分页（只读查询，可共享）。

    加载时预计算全部前缀索引，按键查询 O(1)——组合区每个字母都触发
    一次查询，不做预计算的话每次都要遍历全部拼音合并排序（掌机上
    明显卡顿）。索引构建是首次使用（懒加载）时的一次性开销。
    """

    def __init__(self, dict_path: str | None = None):
        # 默认路径与字体一致：程序所在目录
        self.dict_path = dict_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "pinyin_dict.json")
        self._table: dict[str, list] | None = None
        self._index: dict[str, list[str]] = {}   # prefix → 排序后的候选

    @property
    def loaded(self) -> bool:
        return self._table is not None

    def load(self) -> bool:
        """加载字典并构建前缀索引（懒加载入口）。"""
        try:
            with open(self.dict_path, encoding="utf-8") as f:
                self._table = json.load(f)
            self._build_index()
            return True
        except (OSError, json.JSONDecodeError):
            return False

    def _build_index(self):
        """预计算全部前缀的候选列表。

        排序规则（每个前缀）：**精确匹配该拼音的字在前**（如打 xi 时
        xi 同音字 西/喜/系… 排最前），其余前缀匹配的字在后（如 xia 的
        下/夏），各层内部按字频降序。多音字去重取最高频。
        """
        buckets: dict[str, dict[str, int]] = {}     # prefix → char → freq
        exacts: dict[str, set[str]] = {}            # 完整拼音 → 其候选字
        exact_top: dict[str, int] = {}              # 完整拼音 → 最高频字
        for key, entries in self._table.items():
            s = exacts.setdefault(key, set())
            exact_top[key] = max((f for _, f in entries), default=0)
            for i in range(1, len(key) + 1):
                bucket = buckets.setdefault(key[:i], {})
                for ch, freq in entries:
                    s.add(ch)
                    if freq > bucket.get(ch, -1):
                        bucket[ch] = freq
        self._index = {
            prefix: [ch for ch, _ in sorted(
                bucket.items(),
                key=lambda kv: (
                    kv[1] == 0,   # 生僻字（频次 0）永远排最后
                    not (kv[1] > 0 and kv[0] in exacts.get(prefix, ())
                         and exact_top.get(prefix, 0) >= EXACT_MIN_FREQ),
                    -kv[1], kv[0]))]
            for prefix, bucket in buckets.items()
        }

    def candidates(self, pinyin: str) -> list[str]:
        """返回该拼音串（前缀匹配）的全部候选。

        精确匹配该拼音的字在前，前缀匹配的字在后，各按频率降序。
        无匹配返回空列表。O(1) 索引查询。
        """
        if not self._table and not self.load():
            return []
        pinyin = pinyin.strip().lower()
        if not pinyin:
            return []
        return self._index.get(pinyin, [])

    def page(self, pinyin: str, page: int = 0) -> tuple[list[str], int]:
        """返回第 page 页（0 起）候选与总页数。page 越界自动夹取。"""
        cands = self.candidates(pinyin)
        total = (len(cands) + PAGE_SIZE - 1) // PAGE_SIZE
        if page < 0:
            page = 0
        elif page >= total:
            page = max(0, total - 1)
        start = page * PAGE_SIZE
        return cands[start:start + PAGE_SIZE], total


class PinyinIME:
    """拼音组合状态机（纯逻辑：无渲染、无按键语义）。

    供 OSK 拼音键盘与外接键盘拼音两个前端复用（各自独立实例，
    组合状态互不干扰；可共享同一个 PinyinEngine 查询实例）。
    """

    def __init__(self, engine: PinyinEngine | None = None,
                 dict_path: str | None = None,
                 space_selects_first: bool = False):
        self.engine = engine or PinyinEngine(dict_path)
        self.buf = ""          # 组合区字母
        self.page = 0          # 候选页码
        # 空格选中第一个候选（外接键盘开启；OSK 默认关闭保持原行为）
        self.space_selects_first = space_selects_first

    # ── 查询（供前端渲染） ──

    @property
    def candidates(self) -> tuple[list[str], int]:
        """当前组合区的 (本页候选, 总页数)。"""
        return self.engine.page(self.buf, self.page)

    # ── 输入路由 ──

    def process(self, seq: str | None) -> str | None:
        """输入一个按键序列。返回要写入终端的文本，None=已消费。

        - 字母 a-z（大小写均收）→ 进组合区
        - 数字：组合区空 → 透传终端；非空 → 1..n 选字（>n 忽略）
        - \177（退格）→ 智能退格：组合区有字删组合，空则透传终端
        - + / - → 组合区有内容时翻页，空则透传终端（打加减号不受影响）
        - \r（回车）→ 组合区有字提交原文（兜底），空则透传
        - \x1b（Esc）→ 组合区有字清空组合区，空则透传（保护 vim 的 Esc）
        - 组合区有内容时 ␣/,/. 被吞（否则退格只删组合，符号无法删）
        - 其余透传（控制字符、Alt 组合等）
        """
        if seq is None:
            return None

        # 字母 → 组合区
        if len(seq) == 1 and seq.lower() in "abcdefghijklmnopqrstuvwxyz":
            self.buf += seq.lower()
            self.page = 0
            return None

        # 数字 → 选字 / 透传
        if len(seq) == 1 and seq.isdigit():
            if not self.buf:
                return seq          # 组合区空 → 正常输数字
            cands, _ = self.candidates
            idx = int(seq) - 1
            if 0 <= idx < len(cands):
                out = cands[idx]
                self.buf = ""
                self.page = 0
                return out          # 选中汉字 → 终端
            return None             # 无此候选 → 忽略

        # 智能退格
        if seq == "\177":
            if self.buf:
                self.buf = self.buf[:-1]
                self.page = 0
                return None
            return "\177"           # 组合区空 → 透传终端

        # 候选翻页（组合区空时透传，可正常输入加减号）
        if seq in ("+", "-"):
            if not self.buf:
                return seq
            self._page(1 if seq == "+" else -1)
            return None

        # Enter 兜底：提交原始拼音
        if seq in ("\r", "\n"):
            if self.buf:
                out = self.buf
                self.buf = ""
                self.page = 0
                return out
            return "\r"

        # 空格：候选区有可选项且开启 space_selects_first → 选中第一个
        if seq == " ":
            if not self.buf:
                return " "          # 组合区空 → 透传
            if self.space_selects_first:
                cands, _ = self.candidates
                if cands:
                    out = cands[0]
                    self.buf = ""
                    self.page = 0
                    return out
            return None             # 组合区有内容：吞掉（原行为）

        # 组合区有内容时，逗号/句号不进终端——
        # 否则 backspace 只能删组合区，误输入的符号无法删除
        if self.buf and seq in (",", "."):
            return None

        # Esc：组合区有内容时清空（不回终端），空则透传
        if seq == "\x1b":
            if self.buf:
                self.buf = ""
                self.page = 0
                return None
            return "\x1b"

        return seq

    # ── 控制 ──

    def reset(self):
        """清空组合区与页码（切换输入法/选中后调用）。"""
        self.buf = ""
        self.page = 0

    def page_prev(self):
        """候选上一页（L1/− 等前端按键直接调用）。"""
        self._page(-1)

    def page_next(self):
        """候选下一页（R1/+ 等前端按键直接调用）。"""
        self._page(1)

    def _page(self, delta: int):
        """候选翻页（+1 下一页 / -1 上一页）。无候选或单页时无操作。"""
        _, total = self.candidates
        if total <= 1:
            return
        self.page += delta
        self.page = max(0, min(self.page, total - 1))
