"""SimpleTerminalPy — PTY 伪终端通信层。

对应 C 版 vt100.c 中的 tty_new(), tty_read(), tty_write(),
tty_resize() 以及 main.c 中的 tty_thread()。
"""

import codecs
import os
import pty
import struct
import termios
import fcntl
import select
import signal
import threading

from config import DEFAULT_SHELL


class PtyHandler:
    """管理 PTY 的创建、读写和生命周期。"""

    def __init__(self, shell_path: str = DEFAULT_SHELL,
                 term_name: str = "linux",
                 cmd_list: list[str] | None = None):
        self.shell_path = shell_path
        self.term_name = term_name
        self.cmd_list = cmd_list or []

        self.master_fd: int = -1
        self.child_pid: int = -1
        self.running = True

        # 回调 — 外部设置
        self.on_data: callable = None     # 收到 PTY 输出时调用
        self.on_child_exit: callable = None  # 子进程退出时调用

        self._thread: threading.Thread | None = None

        # 增量 UTF-8 解码器 — 跨 read 块缓存残字节
        # （对齐 C 版 tty_read 的 static buf + memmove 残字节方案，
        #   避免 4096 边界处多字节字符被拆开产生 �）
        self._decoder = codecs.getincrementaldecoder('utf-8')('replace')

    # ── 创建 PTY ──────────────────────────────────────

    def spawn(self, rows: int = 24, cols: int = 80):
        """创建 PTY，fork 子进程执行 shell。"""
        self.master_fd, self.slave_fd = pty.openpty()

        # 设置初始终端窗口大小
        self._set_winsize(rows, cols)

        self.child_pid = os.fork()
        if self.child_pid == 0:
            # ── 子进程 ──
            os.close(self.master_fd)
            self._child_setup()
            # 不期望到达这里
            os._exit(1)

        # ── 父进程 ──
        os.close(self.slave_fd)
        # 设置 master_fd 为非阻塞（select 会处理阻塞等待）
        flags = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
        fcntl.fcntl(self.master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        # 忽略 SIGCHLD — 我们用 PTY EOF 检测子进程退出
        signal.signal(signal.SIGCHLD, signal.SIG_DFL)

    def _child_setup(self):
        """子进程初始化：设置终端并 exec shell。"""
        # 确保 stdin/stdout/stderr 都设成 slave_fd
        # C 版还要处理 ioctl TIOCSCTTY，这里在 openpty 里已自动完成
        try:
            os.setsid()
            os.dup2(self.slave_fd, 0)
            os.dup2(self.slave_fd, 1)
            os.dup2(self.slave_fd, 2)
            if self.slave_fd > 2:
                os.close(self.slave_fd)

            # 设置环境变量
            os.environ["TERM"] = self.term_name
            os.environ.pop("COLUMNS", None)
            os.environ.pop("LINES", None)
            os.environ.pop("TERMCAP", None)  # type: ignore

            # 确保 HOME 并进入用户主目录
            # （C 版 exec_sh 有 chdir(getenv("HOME")) —
            #   掌机菜单环境可能没有 HOME 且 cwd 为 /）
            home = os.environ.get("HOME") or os.path.expanduser("~") or "/"
            os.environ["HOME"] = home
            try:
                os.chdir(home)
            except OSError:
                pass

            # 补全 PATH — 从掌机菜单等精简环境启动时，
            # 常见用户路径（nvm node bin、~/.local/bin 等）可能缺失，
            # 导致 claude 等用户工具找不到。
            self._augment_path()

            # 执行启动命令（-r 选项）
            for cmd in self.cmd_list:
                print(f"\n$ {cmd}")
                os.system(cmd)

            # exec shell
            shell_name = os.path.basename(self.shell_path)
            os.execvp(self.shell_path,
                       [shell_name, "-i"])
        except Exception as e:
            print(f"Child setup failed: {e}", file=__import__('sys').stderr)
            os._exit(1)

    @staticmethod
    def _augment_path():
        """把常见用户 bin 目录加入 PATH（幂等，只加存在的目录）。"""
        home = os.path.expanduser("~")
        existing = [p for p in os.environ.get("PATH", "").split(":") if p]

        extra = [
            os.path.join(home, ".local/bin"),
            os.path.join(home, "bin"),
        ]
        # nvm 的 node bin（claude 等 npm 全局工具）
        nvm_dir = os.path.join(home, ".nvm", "versions", "node")
        if os.path.isdir(nvm_dir):
            for ver in sorted(os.listdir(nvm_dir)):
                b = os.path.join(nvm_dir, ver, "bin")
                if os.path.isdir(b):
                    extra.append(b)

        for p in extra:
            if p not in existing and os.path.isdir(p):
                existing.insert(0, p)
        os.environ["PATH"] = ":".join(existing)

    def _set_winsize(self, rows: int, cols: int):
        """设置 PTY 窗口大小。"""
        if self.master_fd >= 0:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)

    # ── PTY 读取线程 ──────────────────────────────────

    def _decode(self, data: bytes) -> str:
        """增量 UTF-8 解码：残字节缓存到下一块，跨块字符完整重组。"""
        return self._decoder.decode(data)

    def start_reader_thread(self):
        """启动子线程，阻塞等待 PTY 输出。"""
        self._thread = threading.Thread(
            target=self._reader_loop, daemon=True, name="pty-reader")
        self._thread.start()

    def _reader_loop(self):
        """子线程：select() 阻塞等待 PTY 输出，读到数据调 on_data。"""
        while self.running and self.master_fd >= 0:
            try:
                r, _, _ = select.select([self.master_fd], [], [], 1.0)
                if self.master_fd not in r:
                    continue

                data = os.read(self.master_fd, 4096)
                if not data:
                    # EOF — 子进程已退出
                    self.running = False
                    if self.on_child_exit:
                        self.on_child_exit()
                    break

                text = self._decode(data)
                if self.on_data:
                    self.on_data(text)

            except OSError:
                self.running = False
                break

    # ── PTY 写入 ──────────────────────────────────────

    def write(self, s: bytes | str):
        """向 PTY 写入数据。"""
        if self.master_fd < 0:
            return
        if isinstance(s, str):
            s = s.encode('utf-8')
        try:
            os.write(self.master_fd, s)
        except OSError:
            pass

    # ── 窗口 resize ───────────────────────────────────

    def resize(self, rows: int, cols: int):
        """通知子进程终端尺寸变化。"""
        if self.master_fd >= 0:
            self._set_winsize(rows, cols)

    # ── 清理 ──────────────────────────────────────────

    def shutdown(self):
        """清理 PTY 资源。"""
        self.running = False
        if self.master_fd >= 0:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = -1

        # 发送 SIGHUP 结束子进程
        if self.child_pid > 0:
            try:
                os.kill(self.child_pid, signal.SIGHUP)
                os.waitpid(self.child_pid, os.WNOHANG)
            except OSError:
                pass
            self.child_pid = -1
