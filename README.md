# Wireless Display - Windows 11 无线副屏

将其他设备作为 Windows 11 的无线扩展副屏，支持画面实时传输和鼠标键盘回传。

## 架构

```
Windows 11 (服务端)                    Linux (客户端)
┌─────────────────────┐   TCP 9876   ┌─────────────────────┐
│  ParsecVDD 虚拟显示器│              │                     │
│  ↓                   │              │                     │
│  mss/dxcam 屏幕捕获 │ ──────────→  │  PyQt5 全屏显示     │
│  JPEG/H.264 编码     │   视频帧     │  JPEG/H.264 解码    │
│  光标位置采集        │ ──────────→  │  光标绘制           │
│                      │   光标坐标   │                     │
│  SendInput 输入注入  │ ←──────────  │  鼠标/键盘事件捕获  │
└─────────────────────┘   输入回传    └─────────────────────┘
```

## 前置条件

| 项目 | Windows 服务端 | UOS 客户端 |
|------|---------------|-----------|
| 系统 | Windows 10/11 | Linux (ARM/x86) |
| Python | 3.8+ | 3.6+ |
| 网络 | 两台设备在同一局域网内，防火墙放行 TCP 9876 端口 |

## 快速开始

### 第一步：Windows 安装虚拟显示器驱动

UOS 要作为真正的**扩展副屏**（非镜像），需要在 Windows 上安装虚拟显示器驱动。

1. **安装 ParsecVDD 驱动**

   运行 `tools/parsec-vdd/parsec-vdd-0.45.0.0.exe`，按提示完成安装。

   > 这是微软签名的 IDD（Indirect Display Driver）驱动，无需开启测试模式。
   > 也可从 GitHub 下载最新版：https://github.com/nomi-san/parsec-vdd/releases

2. **运行 ParsecVDisplay 伴侣程序**

   运行 `tools/parsec-vdd/ParsecVDisplay.exe`，它会出现在系统托盘。

3. **添加虚拟显示器**

   右键托盘图标 → **Add Display**，Windows 会检测到新显示器。

4. **设置扩展显示**

   打开 Windows **设置 → 显示**：
   - 找到新增的显示器（通常是 "ParsecVDA" 开头）
   - 选择 **"扩展这些显示器"**
   - 按需调整分辨率和位置（拖动显示器排列）

5. **确认显示器编号**

   ```bash
   cd wireless-display
   python -m server.main --list-monitors
   ```

   输出示例：
   ```
   [0] 5760x1440 at (-2160,0) (virtual desktop)
   [1] 1920x1200 at (1920,0)  (monitor 1)    ← 物理主屏
   [2] 1920x1080 at (0,0)     (monitor 2)    ← 物理副屏
   [3] 2160x1440 at (-2160,0) (monitor 3)    ← ParsecVDD 虚拟副屏
   ```

   记住虚拟副屏的编号（上例为 `3`）。

### 第二步：Windows 安装服务端依赖

```bash
cd wireless-display
pip install mss Pillow dxcam PyTurboJPEG
```

> - `mss`：屏幕捕获（必装）
> - `Pillow`：图像编码（必装）
> - `dxcam`：GPU 加速捕获（可选，部分虚拟显示器不兼容时自动降级为 mss）
> - `PyTurboJPEG`：SIMD 加速 JPEG 编码（可选，需要系统安装 libturbojpeg）

### 第三步：部署客户端到 UOS

```bash
# 从 Windows 复制项目到 UOS（替换为你的 UOS IP）
scp -r wireless-display/ uos@192.168.137.27:~/

# SSH 登录 UOS
ssh uos@192.168.137.27

# 安装依赖
bash ~/wireless-display/setup_client.sh
```

客户端依赖：
- `PyQt5`：GUI 显示框架（UOS 通常预装）
- `Pillow`：图像处理

### 第四步：启动服务端（Windows）

```bash
cd wireless-display

# JPEG 模式（默认）
python -m server.main --monitor 3 --fps 30 --quality 70

# H.264 模式（推荐，带宽约 4Mbps，需系统安装 ffmpeg）
python -m server.main --monitor 3 --fps 30 --h264 --bitrate 4M

# H.264 + 指定编码器
python -m server.main --monitor 3 --h264 --encoder nvenc

# 如果 dxcam 崩溃，使用 CPU 捕获模式
python -m server.main --monitor 3 --fps 30 --quality 70 --cpu
```

看到以下输出说明启动成功：
```
=== Wireless Display Server ===
  显示器: #3  2160x1440 @ (-2160,0)
  监听:   0.0.0.0:9876
  帧率:   30 FPS,  H.264 bitrate=4M
  等待客户端连接 ...
```

### 第五步：启动客户端（UOS）

```bash
cd ~/wireless-display

# 替换为 Windows 的 IP 地址
python3 -m client.main --host 192.168.137.1
```

客户端会全屏显示并自动连接服务端。连接断开后会自动重连。

## 使用方式

连接成功后：

- **Windows 鼠标移到虚拟副屏区域** → UOS 屏幕上的光标跟随移动
- **在 UOS 上移动鼠标** → 操作 Windows 虚拟副屏
- **拖拽窗口到虚拟副屏** → UOS 上实时显示
- 支持键盘输入回传

### 快捷键（客户端）

| 按键 | 功能 |
|------|------|
| ESC | 退出客户端 |
| F11 | 切换全屏/窗口模式 |

## 参数说明

### 服务端参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--host` | 0.0.0.0 | 监听地址 |
| `--port` | 9876 | 监听端口 |
| `--monitor` | 1 | 显示器编号（用 `--list-monitors` 查看） |
| `--fps` | 30 | 目标帧率 |
| `--quality` | 70 | JPEG 质量 1-100（越高画质越好，带宽越大） |
| `--h264` | - | 启用 H.264 编码模式（替代 JPEG，需 ffmpeg） |
| `--bitrate` | 4M | H.264 码率（如 2M、4M、8M） |
| `--encoder` | auto | H.264 编码器：auto/nvenc/qsv/amf/mf/cpu |
| `--cpu` | - | 强制 CPU 捕获模式（禁用 dxcam） |
| `--list-monitors` | - | 列出所有显示器并退出 |

### 客户端参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--host` | (必填) | 服务端 IP 地址 |
| `--port` | 9876 | 服务端端口 |

## 常见问题

### Q: UOS 端没有画面
- 检查 Windows 防火墙是否放行了 TCP 9876 端口
- 确认两台设备在同一局域网，`ping` 对方 IP 通
- 确认服务端控制台显示 "客户端已连接"

### Q: dxcam 崩溃 (exit code 0xC0000409)
- 部分虚拟显示器与 DXGI Desktop Duplication 不兼容
- 添加 `--cpu` 参数使用 CPU 捕获模式

### Q: 画面卡顿/延迟高
- **推荐使用 H.264 模式**：`--h264` 可将带宽从 ~17Mbps 降至 ~4Mbps
- 降低分辨率：在 Windows 显示设置中调低虚拟显示器分辨率
- JPEG 模式降低质量：`--quality 50`
- H.264 模式降低码率：`--bitrate 2M`
- 降低帧率：`--fps 20`
- 确保使用 5GHz WiFi 或有线网络

### Q: H.264 模式启动失败
- 确认系统已安装 ffmpeg 并在 PATH 中（`ffmpeg -version` 检查）
- 如果硬件编码器不可用，会自动降级到 libx264 软编码
- 可用 `--encoder cpu` 强制使用软编码

### Q: ParsecVDisplay 托盘没有出现
- 确认 `parsec-vdd-0.45.0.0.exe` 驱动已安装成功
- 重新运行 `ParsecVDisplay.exe`
- 如果仍不行，尝试重启 Windows

## 项目结构

```
wireless-display/
├── common/
│   ├── __init__.py          # 包初始化
│   └── protocol.py          # TCP 帧协议（视频帧、光标位置、输入事件、H.264）
├── server/
│   ├── main.py              # 服务端入口
│   ├── capture.py           # 屏幕捕获（GPU/CPU 双模式）
│   ├── h264_encoder.py      # H.264 编码器（ffmpeg 管道，自动检测硬件编码器）
│   ├── input_inject.py      # Windows 输入注入（SendInput API）
│   └── virtual_display.py   # 虚拟显示器管理
├── client/
│   ├── __init__.py          # 包初始化
│   ├── main.py              # 客户端入口（PyQt5 全屏显示 + 输入捕获）
│   └── h264_decoder.py      # H.264 解码器（ffmpeg 管道，自动检测硬件解码器）
├── docs/
│   └── h264-plan.md         # H.264 实现方案文档
├── tools/
│   └── parsec-vdd/          # ParsecVDD 虚拟显示器驱动
│       ├── parsec-vdd-0.45.0.0.exe   # 驱动安装包
│       └── ParsecVDisplay.exe         # 伴侣程序（托盘管理虚拟显示器）
├── setup_server.bat         # Windows 依赖安装脚本
├── setup_client.sh          # UOS 依赖安装脚本
└── README.md
```

## 协议说明

基于 TCP 的自定义二进制帧协议：

```
[4 字节 大端序 长度][1 字节 类型][payload]
```

| 类型 | 值 | 方向 | 说明 |
|------|-----|------|------|
| VIDEO_FRAME | 0x01 | Server → Client | JPEG 图像数据 |
| CONTROL | 0x02 | 双向 | JSON 控制消息 |
| INPUT | 0x03 | Client → Server | JSON 输入事件 |
| CURSOR_POS | 0x04 | Server → Client | 光标坐标 (2x float32) |
| H264_CHUNK | 0x05 | Server → Client | H.264 编码数据块 |
| STREAM_INFO | 0x06 | Server → Client | 流信息 JSON（宽高、fps、编码器） |
