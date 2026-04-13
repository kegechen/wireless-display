"""
H.264 Encoder — 通过 ffmpeg 子进程管道编码
==========================================
自动检测最佳硬件编码器：h264_nvenc → h264_qsv → h264_amf → h264_mf → libx264
"""

import subprocess
import threading
import queue
import os


# 编码器优先级列表：(名称, ffmpeg 编码器参数)
ENCODER_PRESETS = {
    'nvenc': {
        'codec': 'h264_nvenc',
        'extra': ['-preset', 'p1', '-tune', 'll', '-zerolatency', '1',
                  '-rc', 'cbr'],
    },
    'qsv': {
        'codec': 'h264_qsv',
        'extra': ['-preset', 'veryfast', '-low_power', '1'],
    },
    'amf': {
        'codec': 'h264_amf',
        'extra': ['-quality', 'speed', '-rc', 'cbr'],
    },
    'mf': {
        'codec': 'h264_mf',
        'extra': [],
    },
    'cpu': {
        'codec': 'libx264',
        'extra': ['-preset', 'ultrafast', '-tune', 'zerolatency'],
    },
}

AUTO_PRIORITY = ['nvenc', 'qsv', 'amf', 'mf', 'cpu']


def _find_ffmpeg():
    """查找 ffmpeg 可执行文件路径。"""
    # 优先检查同目录下
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for candidate in [
        os.path.join(script_dir, 'ffmpeg.exe'),
        os.path.join(script_dir, '..', 'ffmpeg.exe'),
    ]:
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)
    # 系统 PATH
    return 'ffmpeg'


def _test_encoder(ffmpeg_path, codec_name):
    """测试编码器是否可用（快速探测）。"""
    try:
        cmd = [
            ffmpeg_path, '-hide_banner', '-f', 'lavfi', '-i',
            'nullsrc=s=64x64:d=0.1', '-c:v', codec_name,
            '-f', 'null', '-'
        ]
        r = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=10, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        return r.returncode == 0
    except Exception:
        return False


def detect_best_encoder(ffmpeg_path=None, preferred=None):
    """自动检测可用的最佳硬件编码器，返回 preset key。"""
    ffmpeg_path = ffmpeg_path or _find_ffmpeg()

    if preferred and preferred != 'auto':
        if preferred in ENCODER_PRESETS:
            codec = ENCODER_PRESETS[preferred]['codec']
            if _test_encoder(ffmpeg_path, codec):
                return preferred
            print(f"  [!] 指定的编码器 {preferred}({codec}) 不可用，尝试自动检测")
        else:
            print(f"  [!] 未知编码器 '{preferred}'，尝试自动检测")

    for key in AUTO_PRIORITY:
        codec = ENCODER_PRESETS[key]['codec']
        print(f"  [?] 测试编码器: {codec} ...", end=' ', flush=True)
        if _test_encoder(ffmpeg_path, codec):
            print("OK")
            return key
        print("不可用")

    raise RuntimeError("没有找到可用的 H.264 编码器，请确认 ffmpeg 已安装")


class H264Encoder:
    """管理 ffmpeg H.264 编码子进程，通过 stdin/stdout 管道传递数据。"""

    def __init__(self, width, height, fps=30, bitrate='4M', encoder='auto'):
        self.width = width
        self.height = height
        self.fps = fps
        self.bitrate = bitrate
        self.frame_size = width * height * 3  # RGB24
        self.ffmpeg_path = _find_ffmpeg()
        self._closed = False

        # 检测编码器
        preset_key = detect_best_encoder(self.ffmpeg_path, encoder)
        preset = ENCODER_PRESETS[preset_key]
        self.codec_name = preset['codec']
        print(f"  [H264] 使用编码器: {self.codec_name}")

        # 编码输出队列
        self._queue = queue.Queue(maxsize=60)

        # 构建 ffmpeg 命令
        cmd = [
            self.ffmpeg_path, '-hide_banner', '-loglevel', 'warning',
            # 输入：原始 RGB
            '-f', 'rawvideo', '-pix_fmt', 'rgb24',
            '-s', f'{width}x{height}', '-r', str(fps),
            '-i', 'pipe:0',
            # 编码器
            '-c:v', self.codec_name,
            *preset['extra'],
            '-b:v', str(bitrate), '-bufsize', '500k',
            '-g', str(fps),  # GOP = 1秒
            '-bf', '0',      # 无 B 帧（低延迟）
            '-bsf:v', 'dump_extra',  # 每个 GOP 前带 SPS/PPS
            # 输出：裸 H.264 流
            '-f', 'h264', 'pipe:1',
        ]

        creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            creationflags=creationflags,
        )

        # 启动读取线程
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True, name='h264-encoder-reader')
        self._reader_thread.start()

        # stderr 监控线程
        self._stderr_thread = threading.Thread(
            target=self._stderr_loop, daemon=True, name='h264-encoder-stderr')
        self._stderr_thread.start()

    def encode(self, rgb_bytes):
        """写入一帧 RGB 数据到编码器。"""
        if self._closed or self._proc.poll() is not None:
            raise RuntimeError("编码器进程已退出")
        try:
            self._proc.stdin.write(rgb_bytes)
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise RuntimeError(f"编码器写入失败: {e}")

    def read_chunk(self, timeout=0.1):
        """从队列中读取编码数据块，返回 bytes 或 None。"""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _reader_loop(self):
        """持续从 ffmpeg stdout 读取编码数据。"""
        READ_SIZE = 65536
        try:
            while not self._closed:
                data = self._proc.stdout.read(READ_SIZE)
                if not data:
                    break
                try:
                    self._queue.put(data, timeout=1)
                except queue.Full:
                    # 丢弃旧数据，放入新数据
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        pass
                    self._queue.put(data, timeout=1)
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
                    print(f"  [ffmpeg-enc] {text}")
        except (OSError, ValueError):
            pass

    def close(self):
        """关闭编码器子进程。"""
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
        print("  [H264] 编码器已关闭")
