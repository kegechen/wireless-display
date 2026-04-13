"""
Wireless Display Client (UOS 端)
=================================
连接 Windows 服务端，全屏显示远程桌面画面，
捕获本机鼠标/键盘事件回传给服务端。

用法:
  python3 client/main.py --host 192.168.137.1
  python3 client/main.py --host 192.168.137.1 --port 9876

快捷键:
  ESC   - 退出
  F11   - 切换全屏/窗口模式
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
    make_input_event, make_control_msg, parse_control_msg,
    unpack_cursor_pos,
)

from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, pyqtSignal, QRect, QPoint
from PyQt5.QtGui import QPixmap, QPainter, QCursor, QFont, QPolygon, QColor, QPen, QBrush


# Qt Key -> Windows VK Code 映射表
QT_KEY_TO_VK = {
    Qt.Key_A: 0x41, Qt.Key_B: 0x42, Qt.Key_C: 0x43, Qt.Key_D: 0x44,
    Qt.Key_E: 0x45, Qt.Key_F: 0x46, Qt.Key_G: 0x47, Qt.Key_H: 0x48,
    Qt.Key_I: 0x49, Qt.Key_J: 0x4A, Qt.Key_K: 0x4B, Qt.Key_L: 0x4C,
    Qt.Key_M: 0x4D, Qt.Key_N: 0x4E, Qt.Key_O: 0x4F, Qt.Key_P: 0x50,
    Qt.Key_Q: 0x51, Qt.Key_R: 0x52, Qt.Key_S: 0x53, Qt.Key_T: 0x54,
    Qt.Key_U: 0x55, Qt.Key_V: 0x56, Qt.Key_W: 0x57, Qt.Key_X: 0x58,
    Qt.Key_Y: 0x59, Qt.Key_Z: 0x5A,
    Qt.Key_0: 0x30, Qt.Key_1: 0x31, Qt.Key_2: 0x32, Qt.Key_3: 0x33,
    Qt.Key_4: 0x34, Qt.Key_5: 0x35, Qt.Key_6: 0x36, Qt.Key_7: 0x37,
    Qt.Key_8: 0x38, Qt.Key_9: 0x39,
    Qt.Key_Space: 0x20, Qt.Key_Return: 0x0D, Qt.Key_Enter: 0x0D,
    Qt.Key_Tab: 0x09, Qt.Key_Backspace: 0x08, Qt.Key_Delete: 0x2E,
    Qt.Key_Insert: 0x2D,
    Qt.Key_Left: 0x25, Qt.Key_Up: 0x26, Qt.Key_Right: 0x27, Qt.Key_Down: 0x28,
    Qt.Key_Home: 0x24, Qt.Key_End: 0x23,
    Qt.Key_PageUp: 0x21, Qt.Key_PageDown: 0x22,
    Qt.Key_Shift: 0x10, Qt.Key_Control: 0x11, Qt.Key_Alt: 0x12,
    Qt.Key_CapsLock: 0x14, Qt.Key_NumLock: 0x90,
    Qt.Key_F1: 0x70, Qt.Key_F2: 0x71, Qt.Key_F3: 0x72, Qt.Key_F4: 0x73,
    Qt.Key_F5: 0x74, Qt.Key_F6: 0x75, Qt.Key_F7: 0x76, Qt.Key_F8: 0x77,
    Qt.Key_F9: 0x78, Qt.Key_F10: 0x79, Qt.Key_F11: 0x7A, Qt.Key_F12: 0x7B,
    Qt.Key_Minus: 0xBD, Qt.Key_Equal: 0xBB,
    Qt.Key_BracketLeft: 0xDB, Qt.Key_BracketRight: 0xDD,
    Qt.Key_Semicolon: 0xBA, Qt.Key_Apostrophe: 0xDE,
    Qt.Key_Comma: 0xBC, Qt.Key_Period: 0xBE,
    Qt.Key_Slash: 0xBF, Qt.Key_Backslash: 0xDC,
    Qt.Key_QuoteLeft: 0xC0,
}


class DisplayWindow(QWidget):
    """全屏显示窗口 + 输入捕获"""

    frame_signal = pyqtSignal(bytes)
    status_signal = pyqtSignal(str)
    cursor_signal = pyqtSignal(float, float)

    def __init__(self, server_host, server_port):
        super().__init__()
        self.server_host = server_host
        self.server_port = server_port
        self.sock = None
        self.sock_lock = threading.Lock()
        self.connected = False
        self.running = True
        self.monitor_info = None

        # 当前帧和显示区域
        self.current_pixmap = None
        self.image_rect = QRect()

        # FPS 统计
        self.frame_count = 0
        self.fps_time = time.time()
        self.current_fps = 0.0

        self.setWindowTitle('Wireless Display')
        self.setMouseTracking(True)
        self.setStyleSheet("background-color: black;")
        self.setCursor(QCursor(Qt.BlankCursor))
        self.setMinimumSize(640, 480)

        # 远程光标位置（窗口像素坐标），None 表示不显示
        self.remote_cursor_pos = None

        # 状态文字
        self.status_text = "正在连接 ..."

        # 信号槽
        self.frame_signal.connect(self._on_frame)
        self.status_signal.connect(self._on_status)
        self.cursor_signal.connect(self._on_cursor_pos)

        # 全屏
        self.showFullScreen()

        # 启动网络线程
        self.net_thread = threading.Thread(target=self._network_loop, daemon=True)
        self.net_thread.start()

    # ---- 绘制 ----

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.black)

        if self.current_pixmap and not self.current_pixmap.isNull():
            painter.drawPixmap(self.image_rect, self.current_pixmap)

            # 绘制远程光标（白色箭头 + 黑色边框）
            pos = self.remote_cursor_pos
            if pos is not None:
                self._draw_cursor_arrow(painter, pos.x(), pos.y())

            # FPS 显示
            painter.setPen(Qt.green)
            painter.setFont(QFont('Monospace', 12))
            painter.drawText(10, 25, f"FPS: {self.current_fps:.1f}")
        else:
            # 状态提示
            painter.setPen(Qt.white)
            painter.setFont(QFont('Sans', 20))
            painter.drawText(self.rect(), Qt.AlignCenter, self.status_text)

        painter.end()

    def _draw_cursor_arrow(self, painter, x, y):
        """在 (x,y) 绘制一个标准箭头光标。"""
        # 箭头形状（相对于光标尖端）
        arrow = QPolygon([
            QPoint(x, y),
            QPoint(x, y + 18),
            QPoint(x + 5, y + 14),
            QPoint(x + 9, y + 21),
            QPoint(x + 12, y + 20),
            QPoint(x + 8, y + 13),
            QPoint(x + 13, y + 13),
        ])
        painter.setRenderHint(QPainter.Antialiasing, True)
        # 黑色边框
        painter.setPen(QPen(QColor(0, 0, 0), 1.5))
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.drawPolygon(arrow)

    def _update_image_rect(self):
        if self.current_pixmap is None:
            return
        ws = self.size()
        ps = self.current_pixmap.size()
        # 保持宽高比缩放
        scale = min(ws.width() / ps.width(), ws.height() / ps.height())
        sw = int(ps.width() * scale)
        sh = int(ps.height() * scale)
        x = (ws.width() - sw) // 2
        y = (ws.height() - sh) // 2
        self.image_rect = QRect(x, y, sw, sh)

    def resizeEvent(self, event):
        self._update_image_rect()
        super().resizeEvent(event)

    # ---- 帧更新 ----

    def _on_frame(self, jpeg_data):
        pixmap = QPixmap()
        pixmap.loadFromData(jpeg_data, 'JPEG')
        if not pixmap.isNull():
            self.current_pixmap = pixmap
            self._update_image_rect()

            # FPS 统计
            self.frame_count += 1
            now = time.time()
            dt = now - self.fps_time
            if dt >= 1.0:
                self.current_fps = self.frame_count / dt
                self.frame_count = 0
                self.fps_time = now

            self.update()

    def _on_status(self, text):
        self.status_text = text
        self.current_pixmap = None
        self.update()

    def _on_cursor_pos(self, rel_x, rel_y):
        """根据服务端光标位置更新绘制光标。"""
        if rel_x < 0 or rel_y < 0:
            self.remote_cursor_pos = None
            self.update()
            return
        if self.image_rect.isNull() or self.image_rect.width() == 0:
            return
        wx = self.image_rect.x() + int(rel_x * self.image_rect.width())
        wy = self.image_rect.y() + int(rel_y * self.image_rect.height())
        self.remote_cursor_pos = QPoint(wx, wy)
        self.update()

    # ---- 网络 ----

    def _network_loop(self):
        while self.running:
            try:
                self.status_signal.emit(f"正在连接 {self.server_host}:{self.server_port} ...")
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5.0)
                sock.connect((self.server_host, self.server_port))
                sock.settimeout(None)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)

                with self.sock_lock:
                    self.sock = sock
                    self.connected = True

                self.status_signal.emit("已连接!")

                while self.running and self.connected:
                    msg_type, payload = recv_message(sock)
                    if msg_type == MSG_VIDEO_FRAME:
                        self.frame_signal.emit(payload)
                    elif msg_type == MSG_CURSOR_POS:
                        rx, ry = unpack_cursor_pos(payload)
                        self.cursor_signal.emit(rx, ry)
                    elif msg_type == MSG_CONTROL:
                        ctrl = parse_control_msg(payload)
                        if ctrl.get('cmd') == 'monitor_info':
                            self.monitor_info = ctrl

            except (ConnectionError, OSError, socket.timeout) as e:
                self.status_signal.emit(f"连接断开: {e}\n2 秒后重连 ...")
            finally:
                with self.sock_lock:
                    self.connected = False
                    if self.sock:
                        try:
                            self.sock.close()
                        except OSError:
                            pass
                        self.sock = None

            if self.running:
                time.sleep(2)

    def _send_input(self, event_type, **kwargs):
        with self.sock_lock:
            if not self.connected or not self.sock:
                return
            try:
                send_message(self.sock, MSG_INPUT, make_input_event(event_type, **kwargs))
            except (ConnectionError, OSError):
                pass

    # ---- 坐标映射 ----

    def _get_rel_pos(self, pos):
        """将窗口坐标映射为图像内相对坐标 (0~1)，超出范围返回 None"""
        if self.image_rect.isNull() or self.image_rect.width() == 0:
            return None, None
        rx = (pos.x() - self.image_rect.x()) / self.image_rect.width()
        ry = (pos.y() - self.image_rect.y()) / self.image_rect.height()
        if 0 <= rx <= 1 and 0 <= ry <= 1:
            return rx, ry
        return None, None

    # ---- 鼠标事件 ----

    def mouseMoveEvent(self, event):
        rx, ry = self._get_rel_pos(event.pos())
        if rx is not None:
            self._send_input('mouse_move', x=rx, y=ry)
            # 本地鼠标移动时也更新绘制光标
            self.remote_cursor_pos = event.pos()
            self.update()

    def mousePressEvent(self, event):
        rx, ry = self._get_rel_pos(event.pos())
        if rx is None:
            return
        btn = {Qt.LeftButton: 'left', Qt.RightButton: 'right',
               Qt.MiddleButton: 'middle'}.get(event.button(), 'left')
        self._send_input('mouse_click', button=btn, action='down', x=rx, y=ry)

    def mouseReleaseEvent(self, event):
        rx, ry = self._get_rel_pos(event.pos())
        if rx is None:
            return
        btn = {Qt.LeftButton: 'left', Qt.RightButton: 'right',
               Qt.MiddleButton: 'middle'}.get(event.button(), 'left')
        self._send_input('mouse_click', button=btn, action='up', x=rx, y=ry)

    def wheelEvent(self, event):
        rx, ry = self._get_rel_pos(event.pos())
        if rx is not None:
            delta = event.angleDelta().y() / 120.0
            self._send_input('mouse_scroll', x=rx, y=ry, delta=delta)

    # ---- 键盘事件 ----

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        if event.key() == Qt.Key_F11:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()
            return
        vk = QT_KEY_TO_VK.get(event.key())
        if vk:
            self._send_input('key_down', vk=vk)

    def keyReleaseEvent(self, event):
        vk = QT_KEY_TO_VK.get(event.key())
        if vk:
            self._send_input('key_up', vk=vk)

    # ---- 关闭 ----

    def closeEvent(self, event):
        self.running = False
        with self.sock_lock:
            self.connected = False
            if self.sock:
                try:
                    send_message(self.sock, MSG_CONTROL, make_control_msg('disconnect'))
                    self.sock.close()
                except OSError:
                    pass
                self.sock = None
        event.accept()


def main():
    parser = argparse.ArgumentParser(description='Wireless Display Client (UOS)')
    parser.add_argument('--host', required=True, help='服务端 IP 地址')
    parser.add_argument('--port', type=int, default=9876, help='服务端端口 (默认 9876)')
    args = parser.parse_args()

    app = QApplication(sys.argv)
    window = DisplayWindow(args.host, args.port)
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
