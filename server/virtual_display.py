"""
虚拟显示器管理模块
===================
通过 parsec-vdd 驱动的 IOCTL 接口，程序化创建/销毁虚拟显示器。
虚拟显示器在 Windows 显示设置中表现为真实显示器，可设置扩展/复制。

驱动设备路径: \\\\.\\ParsecVDA
IOCTL:
  ADD    = 0x002A8004  创建一个虚拟显示器
  REMOVE = 0x002A8008  移除指定虚拟显示器
  UPDATE = 0x002A800C  更新显示器设置
"""

import ctypes
from ctypes import wintypes
import time

# --- parsec-vdd IOCTL 常量 ---
DEVICE_PATH = r"\\.\ParsecVDA"
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80

# CTL_CODE(FILE_DEVICE_BUS_EXTENDER=0x2A, Function, METHOD_BUFFERED=0, FILE_WRITE_ACCESS=0x2)
IOCTL_ADD = 0x002A8004     # Function=0x001
IOCTL_REMOVE = 0x002A8008  # Function=0x002
IOCTL_UPDATE = 0x002A800C  # Function=0x003

kernel32 = ctypes.windll.kernel32


class VirtualDisplay:
    """parsec-vdd 虚拟显示器管理器。

    注意: 设备句柄必须保持打开状态，关闭后虚拟显示器会自动消失。
    """

    def __init__(self):
        self.handle = None
        self.display_count = 0

    def is_driver_installed(self):
        """检查 parsec-vdd 驱动是否已安装"""
        h = kernel32.CreateFileW(
            DEVICE_PATH, GENERIC_WRITE, 0, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None
        )
        if h == -1 or h == 0xFFFFFFFF:
            return False
        kernel32.CloseHandle(h)
        return True

    def open(self):
        """打开 parsec-vdd 设备（必须保持打开）"""
        if self.handle is not None:
            return True
        h = kernel32.CreateFileW(
            DEVICE_PATH, GENERIC_WRITE, 0, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None
        )
        if h == -1 or h == 0xFFFFFFFF:
            err = ctypes.GetLastError()
            raise OSError(
                f"无法打开 ParsecVDA 设备 (error {err})。"
                f"请先安装 parsec-vdd 驱动。"
            )
        self.handle = h
        return True

    def add_display(self):
        """创建一个虚拟显示器，返回 True/False"""
        if self.handle is None:
            self.open()
        bytes_returned = wintypes.DWORD(0)
        result = kernel32.DeviceIoControl(
            self.handle, IOCTL_ADD,
            None, 0, None, 0,
            ctypes.byref(bytes_returned), None,
        )
        if result:
            self.display_count += 1
            return True
        err = ctypes.GetLastError()
        print(f"  [ERR] 创建虚拟显示器失败 (error {err})")
        return False

    def remove_display(self, index=0):
        """移除指定索引的虚拟显示器"""
        if self.handle is None:
            return False
        bytes_returned = wintypes.DWORD(0)
        in_buf = (ctypes.c_byte * 1)(index)
        result = kernel32.DeviceIoControl(
            self.handle, IOCTL_REMOVE,
            in_buf, 1, None, 0,
            ctypes.byref(bytes_returned), None,
        )
        if result:
            self.display_count = max(0, self.display_count - 1)
        return bool(result)

    def close(self):
        """关闭设备句柄（虚拟显示器会自动消失）"""
        if self.handle is not None:
            # 先移除所有虚拟显示器
            for i in range(self.display_count):
                self.remove_display(i)
            kernel32.CloseHandle(self.handle)
            self.handle = None
            self.display_count = 0

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()


def list_monitors():
    """列出所有可用显示器"""
    import mss
    sct = mss.mss()
    monitors = sct.monitors
    result = []
    for i, m in enumerate(monitors):
        label = "虚拟桌面(所有屏幕)" if i == 0 else f"显示器 {i}"
        result.append({
            'index': i, 'label': label,
            'left': m['left'], 'top': m['top'],
            'width': m['width'], 'height': m['height'],
        })
    return result


def find_new_monitor(before_monitors, after_monitors):
    """对比前后显示器列表，找到新增的显示器索引"""
    if len(after_monitors) <= len(before_monitors):
        return None
    # 新增的显示器通常在列表末尾
    return len(after_monitors) - 1


def setup_virtual_display():
    """交互式设置虚拟显示器，返回 (VirtualDisplay实例, 新显示器索引)"""
    vd = VirtualDisplay()

    if not vd.is_driver_installed():
        print("  [!] parsec-vdd 驱动未安装")
        print("  请先运行: D:\\src\\wireless-display\\tools\\parsec-vdd\\parsec-vdd-0.45.0.0.exe")
        return None, None

    import mss

    # 记录当前显示器
    before = mss.mss().monitors
    print(f"  当前显示器数量: {len(before) - 1}")

    # 创建虚拟显示器
    vd.open()
    if not vd.add_display():
        print("  [!] 创建虚拟显示器失败")
        vd.close()
        return None, None

    # 等待 Windows 识别新显示器
    time.sleep(2)

    # 检测新显示器
    after = mss.mss().monitors
    print(f"  创建后显示器数量: {len(after) - 1}")

    new_idx = find_new_monitor(before, after)
    if new_idx:
        m = after[new_idx]
        print(f"  [OK] 新虚拟显示器: #{new_idx} {m['width']}x{m['height']} @ ({m['left']},{m['top']})")
    else:
        print("  [WARN] 未检测到新显示器，可能需要在 Windows 显示设置中启用")
        new_idx = len(after) - 1

    return vd, new_idx


if __name__ == '__main__':
    vd = VirtualDisplay()
    if vd.is_driver_installed():
        print("parsec-vdd 驱动: 已安装")
        print("\n创建虚拟显示器...")
        vd, idx = setup_virtual_display()
        if vd:
            print(f"\n虚拟显示器已创建 (monitor #{idx})")
            print("请在 Windows 显示设置中将其设为'扩展这些显示器'")
            print("按 Enter 关闭虚拟显示器...")
            input()
            vd.close()
            print("虚拟显示器已移除")
    else:
        print("parsec-vdd 驱动: 未安装")
        print("请先安装驱动: tools/parsec-vdd/parsec-vdd-0.45.0.0.exe")

    print("\n当前显示器列表:")
    for m in list_monitors():
        print(f"  [{m['index']}] {m['label']}: {m['width']}x{m['height']} @ ({m['left']},{m['top']})")
