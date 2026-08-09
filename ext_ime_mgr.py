"""ext_ime_mgr.py — 外接键盘输入法门面（main.py 入口）。

管理外接键盘输入法实例（当前只有拼音；未来加五笔等时扩为多实例），
对外提供稳定接口：active / toggle() / handle(seq) / deactivate()。
组合条渲染数据通过 buf / candidates / page 属性暴露给 renderer。
"""

from ext_ime.ext_ime_pinyin import ExtIMEPinyin
from pinyin_ime import PinyinEngine


class ExtIMEManager:
    """外接键盘输入法门面。"""

    def __init__(self, engine: PinyinEngine | None = None):
        self._imes: dict[str, object] = {
            "pinyin": ExtIMEPinyin(engine=engine),
        }
        self.current = "pinyin"

    @property
    def ime(self):
        """当前输入法。"""
        return self._imes[self.current]

    @property
    def active(self) -> bool:
        return self.ime.active

    def toggle(self):
        """Ctrl+Space 切换当前输入法开/关。"""
        self.ime.toggle()

    def deactivate(self):
        """关闭当前输入法（OSK 打开时由 main 调用）。"""
        self.ime.deactivate()

    def handle(self, seq: str | None) -> str | None:
        """键盘输入路由（未激活时原样返回）。"""
        return self.ime.handle(seq)

    # ── 组合条渲染数据（renderer 每帧读取） ──

    @property
    def buf(self) -> str:
        return self.ime.ime.buf

    @property
    def candidates(self) -> tuple[list[str], int]:
        return self.ime.ime.candidates

    @property
    def page(self) -> int:
        return self.ime.ime.page
