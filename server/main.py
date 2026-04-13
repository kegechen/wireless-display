"""
Wireless Display Server (Windows 端)
=====================================
捕获指定显示器画面，通过 TCP 流式推送 JPEG 帧到客户端，
同时接收客户端的鼠标/键盘输入事件并注入到 Windows。

用法:
  python server/main.py --virtual-display    # 自动创建虚拟副屏并捕获
  python server/main.py --monitor 2          # 捕获第2个显示器
  python server/main.py --list-monitors      # 列出所有显示器
  python server/main.py --fps 30 --quality 70
"""

import sys
import os
import socket
import threading
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.protocol import (
    MSG_VIDEO_FRAME, MSG_CONTROL, MSG_INPUT, MSG_CURSOR_POS,
    send_message, recv_message,
    make_control_msg, parse_control_msg, parse_input_event,
    pack_cursor_pos,
)
import ctypes
from server.capture import ScreenCapture
from server.input_inject import InputInjector


class WirelessDisplayServer:
    def __init__(self, host='0.0.0.0', port=9876, monitor=1, fps=30, quality=70, force_cpu=False):
        self.host = host
        self.port = port
        self.target_fps = fps
        self.running = False
        self.client_conn = None
        self.lock = threading.Lock()
        self.vdisplay = None  # 虚拟显示器实例

        self.capture = ScreenCapture(monitor_index=monitor, quality=quality, force_cpu=force_cpu)
        self.injector = InputInjector(self.capture.get_monitor_info())

    def start(self):
        self.running = True
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen(1)
        srv.settimeout(1.0)

        info = self.capture.get_monitor_info()
        print(f"=== Wireless Display Server ===")
        print(f"  显示器: #{self.capture.monitor_index}  {info['width']}x{info['height']} @ ({info['left']},{info['top']})")
        print(f"  监听:   {self.host}:{self.port}")
        print(f"  帧率:   {self.target_fps} FPS,  JPEG quality={self.capture.quality}")
        print(f"  等待客户端连接 ...\n")

        try:
            while self.running:
                try:
                    conn, addr = srv.accept()
                except socket.timeout:
                    continue

                print(f"  [+] 客户端已连接: {addr}")
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                # 增大发送缓冲区
                conn.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024 * 1024)

                with self.lock:
                    self.client_conn = conn

                # 发送显示器信息
                send_message(conn, MSG_CONTROL, make_control_msg('monitor_info', **info))

                # 启动接收输入线程
                recv_t = threading.Thread(target=self._recv_loop, args=(conn,), daemon=True)
                recv_t.start()

                # 主线程发送帧
                self._stream_loop(conn)

                with self.lock:
                    self.client_conn = None
                print(f"  [-] 客户端已断开，等待重连 ...\n")

        except KeyboardInterrupt:
            print("\n正在关闭 ...")
        finally:
            self.running = False
            srv.close()
            if self.vdisplay:
                print("  移除虚拟显示器 ...")
                self.vdisplay.close()
                self.vdisplay = None

    def _get_cursor_rel_pos(self):
        """获取 Windows 光标相对于捕获显示器的归一化坐标 (0~1)，不在此显示器返回 None。"""
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        info = self.capture.get_monitor_info()
        rx = (pt.x - info['left']) / info['width']
        ry = (pt.y - info['top']) / info['height']
        if 0 <= rx <= 1 and 0 <= ry <= 1:
            return rx, ry
        return None

    def _stream_loop(self, conn):
        """捕获屏幕并发送 JPEG 帧"""
        interval = 1.0 / self.target_fps
        stats_time = time.time()
        frame_count = 0
        byte_count = 0

        while self.running:
            t0 = time.time()
            try:
                jpeg = self.capture.capture_jpeg()
                send_message(conn, MSG_VIDEO_FRAME, jpeg)

                # 发送光标位置（轻量 8 字节）
                cursor = self._get_cursor_rel_pos()
                if cursor:
                    send_message(conn, MSG_CURSOR_POS, pack_cursor_pos(*cursor))
                else:
                    # 光标不在此显示器上，发送 (-1,-1) 表示隐藏
                    send_message(conn, MSG_CURSOR_POS, pack_cursor_pos(-1.0, -1.0))

                frame_count += 1
                byte_count += len(jpeg)

                now = time.time()
                if now - stats_time >= 5.0:
                    fps = frame_count / (now - stats_time)
                    mbps = byte_count * 8 / (now - stats_time) / 1_000_000
                    avg_kb = byte_count / frame_count / 1024
                    print(f"  [STAT] {fps:.1f} FPS | {mbps:.1f} Mbps | {avg_kb:.0f} KB/帧")
                    stats_time = now
                    frame_count = 0
                    byte_count = 0

            except (ConnectionError, BrokenPipeError, OSError):
                break

            elapsed = time.time() - t0
            sleep = interval - elapsed
            if sleep > 0:
                time.sleep(sleep)

    def _recv_loop(self, conn):
        """接收客户端输入事件"""
        while self.running:
            try:
                msg_type, payload = recv_message(conn)
                if msg_type == MSG_INPUT:
                    event = parse_input_event(payload)
                    self.injector.handle_event(event)
                elif msg_type == MSG_CONTROL:
                    ctrl = parse_control_msg(payload)
                    if ctrl.get('cmd') == 'disconnect':
                        break
            except (ConnectionError, OSError):
                break
            except Exception as e:
                print(f"  [ERR] 处理输入: {e}")


def main():
    parser = argparse.ArgumentParser(description='Wireless Display Server (Windows)')
    parser.add_argument('--host', default='0.0.0.0', help='监听地址 (默认 0.0.0.0)')
    parser.add_argument('--port', type=int, default=9876, help='监听端口 (默认 9876)')
    parser.add_argument('--monitor', type=int, default=1, help='显示器编号 (1=主屏, 2=副屏...)')
    parser.add_argument('--fps', type=int, default=30, help='目标帧率 (默认 30)')
    parser.add_argument('--quality', type=int, default=70, help='JPEG 质量 1-100 (默认 70)')
    parser.add_argument('--list-monitors', action='store_true', help='列出所有显示器并退出')
    parser.add_argument('--virtual-display', action='store_true',
                        help='自动创建 parsec-vdd 虚拟显示器作为副屏')
    parser.add_argument('--cpu', action='store_true',
                        help='强制 CPU 捕获模式 (禁用 dxcam/DXGI)')
    args = parser.parse_args()

    if args.list_monitors:
        import mss
        sct = mss.mss()
        print("Available monitors:")
        for i, m in enumerate(sct.monitors):
            tag = "(virtual desktop)" if i == 0 else f"(monitor {i})"
            print(f"  [{i}] {m['width']}x{m['height']} at ({m['left']},{m['top']}) {tag}")
        return

    vdisplay = None
    monitor = args.monitor

    if args.virtual_display:
        from server.virtual_display import setup_virtual_display
        print("=== 创建虚拟显示器 ===")
        vdisplay, new_idx = setup_virtual_display()
        if vdisplay is None:
            print("[!] 虚拟显示器创建失败，退出")
            return
        monitor = new_idx
        print(f"  将捕获虚拟显示器 #{monitor}\n")

    server = WirelessDisplayServer(
        host=args.host, port=args.port,
        monitor=monitor, fps=args.fps, quality=args.quality,
        force_cpu=args.cpu,
    )
    server.vdisplay = vdisplay
    server.start()


if __name__ == '__main__':
    main()
