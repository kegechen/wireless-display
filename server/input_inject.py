"""
Windows 输入注入模块
使用 ctypes + SendInput API 将远程输入事件注入到对应显示器坐标
"""

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

# --- Constants ---
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


# --- Structures ---
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("ii", INPUT_UNION),
    ]


class InputInjector:
    """将远程 UOS 端的输入事件注入到 Windows 虚拟桌面的指定显示器区域"""

    def __init__(self, monitor_rect):
        """
        monitor_rect: dict with keys left, top, width, height
                      表示目标显示器在虚拟桌面中的位置
        """
        self.monitor = monitor_rect
        self._update_virtual_screen()

    def _update_virtual_screen(self):
        self.virt_x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        self.virt_y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        self.virt_w = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        self.virt_h = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

    def _to_absolute(self, rel_x, rel_y):
        """Convert relative coords (0~1) to SendInput absolute coords (0~65535)."""
        px = self.monitor['left'] + rel_x * self.monitor['width']
        py = self.monitor['top'] + rel_y * self.monitor['height']
        abs_x = int((px - self.virt_x) / self.virt_w * 65535)
        abs_y = int((py - self.virt_y) / self.virt_h * 65535)
        return max(0, min(65535, abs_x)), max(0, min(65535, abs_y))

    def _send_mouse(self, dx, dy, flags, mouse_data=0):
        extra = ctypes.c_ulong(0)
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.ii.mi.dx = dx
        inp.ii.mi.dy = dy
        inp.ii.mi.mouseData = ctypes.c_ulong(mouse_data).value
        inp.ii.mi.dwFlags = flags
        inp.ii.mi.time = 0
        inp.ii.mi.dwExtraInfo = ctypes.pointer(extra)
        user32.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(inp))

    def _send_key(self, vk, flags):
        extra = ctypes.c_ulong(0)
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.ii.ki.wVk = vk
        inp.ii.ki.wScan = 0
        inp.ii.ki.dwFlags = flags
        inp.ii.ki.time = 0
        inp.ii.ki.dwExtraInfo = ctypes.pointer(extra)
        user32.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(inp))

    def mouse_move(self, rel_x, rel_y):
        ax, ay = self._to_absolute(rel_x, rel_y)
        self._send_mouse(ax, ay, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK)

    def mouse_click(self, rel_x, rel_y, button='left', action='down'):
        ax, ay = self._to_absolute(rel_x, rel_y)
        flag_map = {
            ('left', 'down'): MOUSEEVENTF_LEFTDOWN,
            ('left', 'up'): MOUSEEVENTF_LEFTUP,
            ('right', 'down'): MOUSEEVENTF_RIGHTDOWN,
            ('right', 'up'): MOUSEEVENTF_RIGHTUP,
            ('middle', 'down'): MOUSEEVENTF_MIDDLEDOWN,
            ('middle', 'up'): MOUSEEVENTF_MIDDLEUP,
        }
        flag = flag_map.get((button, action))
        if flag is None:
            return
        self._send_mouse(ax, ay, flag | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK)

    def mouse_scroll(self, rel_x, rel_y, delta):
        ax, ay = self._to_absolute(rel_x, rel_y)
        self._send_mouse(ax, ay,
                         MOUSEEVENTF_WHEEL | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
                         int(delta * 120))

    def key_event(self, vk_code, action='down'):
        flags = 0 if action == 'down' else KEYEVENTF_KEYUP
        # Extended keys (arrows, ins, del, home, end, pgup, pgdn, numlock, etc.)
        extended_keys = {0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x24, 0x23, 0x21, 0x22, 0x90}
        if vk_code in extended_keys:
            flags |= KEYEVENTF_EXTENDEDKEY
        self._send_key(vk_code, flags)

    def handle_event(self, event):
        """处理解析后的输入事件 dict"""
        t = event.get('type')
        if t == 'mouse_move':
            self.mouse_move(event['x'], event['y'])
        elif t == 'mouse_click':
            self.mouse_click(event['x'], event['y'],
                             event.get('button', 'left'),
                             event.get('action', 'down'))
        elif t == 'mouse_scroll':
            self.mouse_scroll(event['x'], event['y'], event.get('delta', 0))
        elif t == 'key_down':
            self.key_event(event['vk'], 'down')
        elif t == 'key_up':
            self.key_event(event['vk'], 'up')
