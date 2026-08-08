"""osk_mgr.py — OSK 门面（main.py 唯一入口）。

管理语言键盘实例（英文/拼音），对外暴露稳定接口：

  active / location_bottom      OSK 显隐与位置
  language                     当前语言（"en"/"pinyin"）
  move_up/down/left/right()    光标导航
  press(name)                  语义化动作键 → 要写入终端的文本（None=已消费）
  render() / invalidate()      渲染与缓存失效
  on_l1_press/release、on_r1_press  掌机按键回调（委托当前键盘）

加新语言 = 在 osk/ 加一个键盘类 + 本文件注册一行，main.py 零改动。
"""

from osk.osk_en import OSKEn
from osk.osk_pinyin import OSKPinyin


class OSKManager:
    """OSK 门面 — 语言切换 + 按键分派。"""

    def __init__(self, screen_w: int, screen_h: int,
                 dict_path: str | None = None):
        self.active = True
        self.location_bottom = True   # True=底部, False=顶部
        self.language = "en"          # 当前语言

        self._kbs: dict[str, object] = {
            "en": OSKEn(screen_w, screen_h),
            "pinyin": OSKPinyin(screen_w, screen_h, dict_path),
        }

    @property
    def kb(self):
        """当前语言键盘。"""
        return self._kbs[self.language]

    # ── 语言切换 ──────────────────────────────────────

    def _switch_language(self):
        """语言键（🌐/中/EN）→ 切换语言，清理跨语言状态。"""
        self.language = "pinyin" if self.language == "en" else "en"
        # 清拼音组合区/页码（切换即重新开始）
        self._kbs["pinyin"].pinyin_buf = ""
        self._kbs["pinyin"].pinyin_page = 0
        # 进拼音时清英文 Ctrl/Alt 锁定，避免字母被转成控制字符
        if self.language == "pinyin":
            self._kbs["en"].ctrl = False
            self._kbs["en"].alt = False

    # ── 导航 ──────────────────────────────────────────

    def move_left(self):
        self.kb.move_left()

    def move_right(self):
        self.kb.move_right()

    def move_up(self):
        self.kb.move_up()

    def move_down(self):
        self.kb.move_down()

    # ── 按键（语义化） ─────────────────────────────────

    def press(self, name: str) -> str | None:
        """用户按了动作键 name（a/b/start/select/l2/r2）。

        返回要写入终端的文本，None = 已消费（修饰键/组合区/语言切换）。
        语言切换时返回 None，调用方可通过 language 变化检测
        （用于 OSK 高度变化后的全屏重绘）。
        """
        if name == "a":
            seq = self.kb.press_selected()
            if self.kb.switch_requested:
                self.kb.switch_requested = False
                self._switch_language()
                return None
            return self.kb.process(seq)
        return self.kb.action(name)

    # ── 掌机按键回调（委托当前键盘） ────────────────────

    def on_l1_press(self):
        self.kb.on_l1_press()

    def on_l1_release(self):
        self.kb.on_l1_release()

    def on_r1_press(self):
        self.kb.on_r1_press()

    # ── 渲染 ──────────────────────────────────────────

    def render(self):
        """渲染当前语言键盘为 PIL Image。"""
        return self.kb.render()

    def invalidate(self):
        self.kb.invalidate()
