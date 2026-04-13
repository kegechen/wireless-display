"""
H.264 Decoder — 通过 ffmpeg 子进程管道解码
==========================================
自动检测硬件解码器：h264_v4l2m2m → h264（软解兜底）
"""

import subprocess
import threading
import queue
import os
import platform


# 解码器优先级（按平台）
DECODER_PRIORITY_LINUX_ARM = ['h264_v4l2m2m', 'h264']
DECODER_PRIORITY_DEFAULT = ['h264']


def _find_ffmpeg():
    """查找 ffmpeg 可执行文件路径。"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for candidate in [
        os.path.join(script_dir, 'ffmpeg'),
        os.path.join(script_dir, '..', 'ffmpeg'),
    ]:
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)
    return 'ffmpeg'


def _test_decoder(ffmpeg_path, decoder_name):
    """测试解码器是否可用。"""
    try:
        cmd = [ffmpeg_path, '-hide_banner', '-decoders']
        r = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=10,
        )
        return decoder_name in r.stdout.decode('utf-8', errors='replace')
    except Exception:
        return False


def detect_best_decoder(ffmpeg_path=None):
    """自动检测可用的最佳解码器。"""
    ffmpeg_path = ffmpeg_path or _find_ffmpeg()
    machine = platform.machine().lower()
    is_arm = 'aarch64' in machine or 'arm' in machine

    priority = DECODER_PRIORITY_LINUX_ARM if is_arm else DECODER_PRIORITY_DEFAULT

    for decoder in priority:
        if _test_decoder(ffmpeg_path, decoder):
            return decoder

    return 'h264'  # 兜底软解


class H264Decoder:
    """管理 ffmpeg H.264 解码子进程，通过 stdin/stdout 管道传递数据。"""

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.frame_size = width * height * 3  # RGB24
        self.ffmpeg_path = _find_ffmpeg()
        self._closed = False

        # 检测解码器
        self.decoder_name = detect_best_decoder(self.ffmpeg_path)
        print(f"  [H264] 使用解码器: {self.decoder_name}")

        # 解码帧队列（只保留最新几帧）
        self._queue = queue.Queue(maxsize=3)

        # 构建 ffmpeg 命令（-c:v 放在 -i 前面，作为输入解码器选项）
        cmd = [
            self.ffmpeg_path, '-hide_banner', '-loglevel', 'warning',
            # 输入解码器 + 裸 H.264 流
            '-c:v', self.decoder_name,
            '-f', 'h264',
            '-i', 'pipe:0',
            # 输出：原始 RGB
            '-f', 'rawvideo', '-pix_fmt', 'rgb24',
            '-s', f'{width}x{height}',
            'pipe:1',
        ]

        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

        # 启动读取线程（从 stdout 读取解码后的 RGB 帧）
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True, name='h264-decoder-reader')
        self._reader_thread.start()

        # stderr 监控线程
        self._stderr_thread = threading.Thread(
            target=self._stderr_loop, daemon=True, name='h264-decoder-stderr')
        self._stderr_thread.start()

    def feed(self, h264_data):
        """将 H.264 编码数据喂给解码器。"""
        if self._closed or self._proc.poll() is not None:
            return
        try:
            self._proc.stdin.write(h264_data)
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def read_frame(self, timeout=0.1):
        """从队列中读取一帧解码后的 RGB 数据，返回 bytes 或 None。"""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _reader_loop(self):
        """持续从 ffmpeg stdout 精确读取完整帧（width*height*3 字节）。"""
        try:
            while not self._closed:
                data = bytearray()
                while len(data) < self.frame_size:
                    chunk = self._proc.stdout.read(self.frame_size - len(data))
                    if not chunk:
                        return  # EOF
                    data.extend(chunk)

                frame = bytes(data)
                # 只保留最新帧，丢弃旧帧
                if self._queue.full():
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        pass
                try:
                    self._queue.put(frame, timeout=0.5)
                except queue.Full:
                    pass
        except (OSError, ValueError):
            pass

    def _stderr_loop(self):
        """读取 ffmpeg stderr 输出用于调试。"""
        try:
            for line in self._proc.stderr:
                if self._closed:
                    break
                text = line.decode('utf-8', errors='replace').strip()
                if text:
                    print(f"  [ffmpeg-dec] {text}")
        except (OSError, ValueError):
            pass

    def close(self):
        """关闭解码器子进程。"""
        if self._closed:
            return
        self._closed = True
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
        except OSError:
            pass
        try:
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass
        print("  [H264] 解码器已关闭")
