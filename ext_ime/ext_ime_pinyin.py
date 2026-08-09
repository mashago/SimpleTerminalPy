"""ext_ime_pinyin.py — 外接键盘拼音输入法（OSK 关闭时，Ctrl+Space 切换）。

组合状态委托给 PinyinIME（self.ime，与 OSK 拼音共用同一状态机逻辑）；
PinyinEngine 查询实例与 OSK 拼音共享（字典只加载一次）。
组合条由 renderer 绘制（光标行上方），本类只负责状态与路由。
"""

from pinyin_ime import PinyinEngine, PinyinIME


class ExtIMEPinyin:
    """外接键盘拼音输入法前端。

    输入来源是外接键盘事件（main.py 转成文本序列后喂给 handle）。
    """

    def __init__(self, engine: PinyinEngine | None = None):
        # 空格选中第一个候选（外接键盘开启；OSK 拼音默认关闭）
        self.ime = PinyinIME(engine=engine, space_selects_first=True)
        self.active = False

    def toggle(self):
        """Ctrl+Space 切换开/关（切换时清空组合区）。"""
        self.active = not self.active
        self.ime.reset()

    def deactivate(self):
        """关闭输入法（OSK 打开时由 main 调用）。"""
        self.active = False
        self.ime.reset()

    def handle(self, seq: str | None) -> str | None:
        """键盘输入路由。返回要写入终端的文本，None=已消费。

        未激活时原样返回（不影响正常键盘输入）。
        """
        if not self.active:
            return seq
        return self.ime.process(seq)
