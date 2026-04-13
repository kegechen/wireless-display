"""
屏幕捕获模块
GPU 优先 (dxcam/DXGI Desktop Duplication) → CPU 兜底 (mss)
"""

import io
import time

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

    def capture_rgb(self):
        """捕获屏幕并返回原始 RGB24 bytes (width*height*3). GPU 优先."""
        if self.gpu_mode:
            return self._capture_dxcam_rgb()
        else:
            return self._capture_mss_rgb()

    def _capture_dxcam_rgb(self):
        """GPU capture via dxcam, 返回 RGB bytes."""
        frame = self._camera.grab()
        if frame is None:
            if hasattr(self, '_last_rgb') and self._last_rgb is not None:
                return self._last_rgb
            time.sleep(0.005)
            frame = self._camera.grab()
            if frame is None:
                return self._last_rgb if hasattr(self, '_last_rgb') else b'\x00' * (self.width * self.height * 3)
        self._last_rgb = frame.tobytes()
        return self._last_rgb

    def _capture_mss_rgb(self):
        """CPU capture via mss, 返回 RGB bytes."""
        screenshot = self._sct.grab(self._monitor_rect)
        return screenshot.rgb

    def capture_jpeg(self):
        """捕获屏幕并返回 JPEG bytes. GPU 优先."""
        if self.gpu_mode:
            return self._capture_dxcam()
        else:
            return self._capture_mss()

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
