"""
屏幕捕获模块
GPU 优先 (dxcam/DXGI Desktop Duplication) → CPU 兜底 (mss)
"""

import io
import time
import ctypes
from ctypes import wintypes

# --- GPU / CPU capture backend selection ---
_USE_DXCAM = False
_USE_TURBOJPEG = False

try:
    import dxcam
    _USE_DXCAM = True
except ImportError:
    pass

try:
    from turbojpeg import TurboJPEG
    _tj = TurboJPEG()
    _USE_TURBOJPEG = True
except Exception:
    pass

import mss
from PIL import Image

# --- Windows cursor capture ---
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

# 设置 argtypes 防止 c_void_p 溢出
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi32.SelectObject.restype = ctypes.c_void_p
gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
gdi32.CreateDIBSection.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
                                    ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_uint]
gdi32.CreateDIBSection.restype = ctypes.c_void_p
gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
gdi32.DeleteDC.restype = wintypes.BOOL
user32.GetDC.argtypes = [ctypes.c_void_p]
user32.GetDC.restype = ctypes.c_void_p
user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.ReleaseDC.restype = ctypes.c_int
user32.DrawIconEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                               ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
user32.DrawIconEx.restype = wintypes.BOOL

HCURSOR = ctypes.c_void_p
HBITMAP = ctypes.c_void_p

class CURSORINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('flags', wintypes.DWORD),
        ('hCursor', HCURSOR),
        ('ptScreenPos', wintypes.POINT),
    ]

class ICONINFO(ctypes.Structure):
    _fields_ = [
        ('fIcon', wintypes.BOOL),
        ('xHotspot', wintypes.DWORD),
        ('yHotspot', wintypes.DWORD),
        ('hbmMask', HBITMAP),
        ('hbmColor', HBITMAP),
    ]

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ('biSize', wintypes.DWORD),
        ('biWidth', wintypes.LONG),
        ('biHeight', wintypes.LONG),
        ('biPlanes', wintypes.WORD),
        ('biBitCount', wintypes.WORD),
        ('biCompression', wintypes.DWORD),
        ('biSizeImage', wintypes.DWORD),
        ('biXPelsPerMeter', wintypes.LONG),
        ('biYPelsPerMeter', wintypes.LONG),
        ('biClrUsed', wintypes.DWORD),
        ('biClrImportant', wintypes.DWORD),
    ]

CURSOR_SHOWING = 0x01
DIB_RGB_COLORS = 0
BI_RGB = 0


def _get_cursor_on_monitor(mon_left, mon_top, mon_w, mon_h):
    """获取光标位置和图像(RGBA PIL Image)，相对于指定显示器。
    返回 (cursor_img, rel_x, rel_y) 或 None（光标不在此显示器上或不可见）。
    """
    ci = CURSORINFO()
    ci.cbSize = ctypes.sizeof(CURSORINFO)
    if not user32.GetCursorInfo(ctypes.byref(ci)):
        return None
    if not (ci.flags & CURSOR_SHOWING):
        return None

    cx, cy = ci.ptScreenPos.x, ci.ptScreenPos.y

    # 获取光标热点偏移
    ii = ICONINFO()
    if not user32.GetIconInfo(ci.hCursor, ctypes.byref(ii)):
        return None
    hotspot_x, hotspot_y = ii.xHotspot, ii.yHotspot

    # 获取光标大小
    cursor_w = user32.GetSystemMetrics(13)  # SM_CXCURSOR
    cursor_h = user32.GetSystemMetrics(14)  # SM_CYCURSOR
    if cursor_w == 0:
        cursor_w = 32
    if cursor_h == 0:
        cursor_h = 32

    # 计算光标在显示器上的位置（左上角）
    draw_x = cx - hotspot_x - mon_left
    draw_y = cy - hotspot_y - mon_top

    # 检查光标是否部分可见于此显示器
    if draw_x + cursor_w <= 0 or draw_x >= mon_w:
        _cleanup_iconinfo(ii)
        return None
    if draw_y + cursor_h <= 0 or draw_y >= mon_h:
        _cleanup_iconinfo(ii)
        return None

    # 渲染光标到 RGBA 图像
    cursor_img = _render_cursor(ci.hCursor, cursor_w, cursor_h)
    _cleanup_iconinfo(ii)

    if cursor_img is None:
        return None

    return cursor_img, draw_x, draw_y


def _render_cursor(hcursor, w, h):
    """使用 DrawIconEx 将光标渲染为 RGBA PIL Image。"""
    hdc_screen = user32.GetDC(None)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)

    # 创建 32-bit BGRA bitmap
    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h  # top-down
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = BI_RGB

    bits = ctypes.c_void_p()
    hbm = gdi32.CreateDIBSection(hdc_mem, ctypes.byref(bmi), DIB_RGB_COLORS,
                                  ctypes.byref(bits), None, 0)
    if not hbm:
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(None, hdc_screen)
        return None

    old_bm = gdi32.SelectObject(hdc_mem, hbm)

    # 填充透明背景
    ctypes.memset(bits, 0, w * h * 4)

    # 绘制光标
    user32.DrawIconEx(hdc_mem, 0, 0, hcursor, w, h, 0, None, 3)  # DI_NORMAL=3

    # 读取像素数据
    buf = (ctypes.c_ubyte * (w * h * 4))()
    ctypes.memmove(buf, bits, w * h * 4)

    gdi32.SelectObject(hdc_mem, old_bm)
    gdi32.DeleteObject(hbm)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(None, hdc_screen)

    # BGRA -> RGBA
    img = Image.frombytes('RGBA', (w, h), bytes(buf), 'raw', 'BGRA')

    # 检查是否全透明（有些光标没有 alpha 通道）
    # 如果全透明，设置非黑色像素为不透明
    alpha = img.split()[3]
    if alpha.getextrema() == (0, 0):
        import numpy as np
        arr = np.array(img)
        mask = (arr[:, :, 0] > 0) | (arr[:, :, 1] > 0) | (arr[:, :, 2] > 0)
        arr[:, :, 3] = mask.astype(np.uint8) * 255
        img = Image.fromarray(arr, 'RGBA')

    return img


def _cleanup_iconinfo(ii):
    """释放 ICONINFO 中的 bitmap 句柄。"""
    if ii.hbmMask:
        gdi32.DeleteObject(ii.hbmMask)
    if ii.hbmColor:
        gdi32.DeleteObject(ii.hbmColor)


class ScreenCapture:
    def __init__(self, monitor_index=1, quality=70, force_cpu=False):
        self.monitor_index = monitor_index
        self.quality = quality
        self.gpu_mode = False

        # Try GPU capture first
        if _USE_DXCAM and not force_cpu:
            try:
                # dxcam output_idx is 0-based (0 = first monitor)
                self._camera = dxcam.create(
                    output_idx=max(0, monitor_index - 1),
                    output_color="RGB",
                )
                # Test grab
                test = self._camera.grab()
                if test is not None:
                    self.gpu_mode = True
                    self.width = test.shape[1]
                    self.height = test.shape[0]
                    print(f"  [GPU] dxcam DXGI capture initialized ({self.width}x{self.height})")
                else:
                    raise RuntimeError("dxcam grab returned None")
            except Exception as e:
                print(f"  [!] dxcam init failed: {e}, falling back to mss")
                self._camera = None
                self.gpu_mode = False

        # CPU fallback
        if not self.gpu_mode:
            self._sct = mss.mss()
            monitors = self._sct.monitors
            if monitor_index >= len(monitors):
                print(f"  [!] Monitor {monitor_index} not found, using primary")
                self.monitor_index = 1
            mon = monitors[self.monitor_index]
            self._monitor_rect = mon
            self.width = mon['width']
            self.height = mon['height']
            print(f"  [CPU] mss capture initialized ({self.width}x{self.height})")

        # Encoding backend info
        if _USE_TURBOJPEG:
            print(f"  [GPU/SIMD] turbojpeg JPEG encoding")
        else:
            print(f"  [CPU] Pillow JPEG encoding")

        # Get monitor geometry for input mapping
        self._fetch_monitor_geometry()

    def _fetch_monitor_geometry(self):
        """Get monitor position in virtual desktop (needed for input coordinate mapping)."""
        sct = mss.mss()
        monitors = sct.monitors
        idx = min(self.monitor_index, len(monitors) - 1)
        mon = monitors[idx]
        self._geometry = {
            'left': mon['left'],
            'top': mon['top'],
            'width': mon['width'],
            'height': mon['height'],
        }

    def get_monitor_info(self):
        return {
            'width': self.width,
            'height': self.height,
            'left': self._geometry['left'],
            'top': self._geometry['top'],
        }

    def list_monitors(self):
        sct = mss.mss()
        return sct.monitors

    def capture_jpeg(self):
        """捕获屏幕并返回 JPEG bytes. GPU 优先."""
        if self.gpu_mode:
            return self._capture_dxcam()
        else:
            return self._capture_mss()

    def _draw_cursor_on_image(self, img):
        """在 PIL Image 上绘制系统光标。"""
        geo = self._geometry
        result = _get_cursor_on_monitor(geo['left'], geo['top'], geo['width'], geo['height'])
        if result is None:
            return img
        cursor_img, dx, dy = result
        # 使用 alpha 合成粘贴光标
        img.paste(cursor_img, (dx, dy), cursor_img)
        return img

    def _capture_dxcam(self):
        """GPU capture via dxcam + JPEG encode."""
        frame = self._camera.grab()
        if frame is None:
            # 画面无变化，返回缓存帧
            if hasattr(self, '_last_jpeg') and self._last_jpeg is not None:
                return self._last_jpeg
            time.sleep(0.005)
            frame = self._camera.grab()
            if frame is None:
                return self._last_jpeg if hasattr(self, '_last_jpeg') else b''

        if _USE_TURBOJPEG:
            jpeg = _tj.encode(frame, quality=self.quality)
        else:
            img = Image.fromarray(frame)
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=self.quality)
            jpeg = buf.getvalue()

        self._last_jpeg = jpeg
        return jpeg

    def _capture_mss(self):
        """CPU capture via mss + JPEG encode."""
        screenshot = self._sct.grab(self._monitor_rect)

        if _USE_TURBOJPEG:
            import numpy as np
            frame = np.frombuffer(screenshot.rgb, dtype=np.uint8).reshape(
                screenshot.height, screenshot.width, 3
            )
            jpeg = _tj.encode(frame, quality=self.quality)
        else:
            img = Image.frombytes('RGB', screenshot.size, screenshot.rgb)
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=self.quality)
            jpeg = buf.getvalue()

        return jpeg

    def close(self):
        if self.gpu_mode and hasattr(self, '_camera') and self._camera:
            try:
                del self._camera
            except Exception:
                pass
