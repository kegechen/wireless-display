# H.264 硬件编码/解码实现计划

## Context

当前无线副屏使用 JPEG 逐帧传输（30fps × ~70KB/帧 ≈ 17Mbps），带宽占用高且无帧间压缩。
需要改为 H.264 编码，利用 Windows GPU 硬件编码 + 客户端硬件解码，将带宽降至 ~4Mbps（约4倍压缩），同时提升流畅性。

## 方案：ffmpeg subprocess 管道

服务端和客户端各起一个 ffmpeg 子进程，通过 stdin/stdout 管道传递数据，无需额外 Python 库。

```
服务端:  mss截屏 → RGB写入ffmpeg.stdin → [h264_nvenc编码] → ffmpeg.stdout读取H264 → TCP发送
客户端:  TCP接收 → ffmpeg.stdin写入H264 → [h264_v4l2m2m解码] → ffmpeg.stdout读取RGB → QImage显示
```

## 协议变更

新增消息类型，兼容现有 JPEG 模式：

| 类型 | 值 | 说明 |
|------|-----|------|
| MSG_H264_CHUNK | 0x05 | H.264 编码数据块 |
| MSG_STREAM_INFO | 0x06 | 流信息（宽高、编码器、fps） |

服务端启动时发送 `MSG_STREAM_INFO`，客户端据此初始化解码器。

## 修改文件

### 1. `common/protocol.py`
- 新增 `MSG_H264_CHUNK = 0x05`、`MSG_STREAM_INFO = 0x06`
- 新增 `make_stream_info()` / `parse_stream_info()` 辅助函数

### 2. `server/h264_encoder.py`（新建）
- `H264Encoder` 类：管理 ffmpeg 编码子进程
- `__init__(width, height, fps, bitrate, codec)`: 启动 ffmpeg 管道
  - 编码器优先级：h264_nvenc → h264_qsv → h264_amf → h264_mf → libx264
  - 低延迟参数：`-tune ll -g {fps} -bf 0 -bsf:v dump_extra`
  - 输入：`-f rawvideo -pix_fmt rgb24 -s WxH pipe:0`
  - 输出：`-f h264 pipe:1`
- `encode(rgb_bytes)`: 写入 stdin，返回缓冲区中的编码数据
- `read_encoded()`: 从 stdout 非阻塞读取编码数据
- `close()`: 关闭 ffmpeg 子进程
- 编码线程：持续从 stdout 读取编码块放入队列

### 3. `server/main.py`
- 新增 `--h264` 参数启用 H.264 模式
- 新增 `--bitrate` 参数（默认 4M）
- 新增 `--encoder` 参数（auto/nvenc/qsv/amf/cpu）
- H.264 模式下：
  - 连接时发送 `MSG_STREAM_INFO`
  - `_stream_loop` 改为：截屏 → encode → 读取编码块 → 发送 `MSG_H264_CHUNK`
- JPEG 模式保持不变（向后兼容）

### 4. `client/h264_decoder.py`（新建）
- `H264Decoder` 类：管理 ffmpeg 解码子进程
- `__init__(width, height)`: 启动 ffmpeg 解码管道
  - 解码器优先级：h264_v4l2m2m → h264_omx_dec → h264（软解兜底）
  - 输入：`-f h264 pipe:0`
  - 输出：`-f rawvideo -pix_fmt rgb24 -s WxH pipe:1`
- `decode(h264_chunk)`: 写入 stdin
- `read_frame()`: 从 stdout 读取一帧 RGB 数据（width × height × 3 字节）
- 解码线程：持续从 stdout 读取完整帧放入队列

### 5. `client/main.py`
- 网络接收循环处理 `MSG_STREAM_INFO` 和 `MSG_H264_CHUNK`
- 收到 `MSG_STREAM_INFO` 时初始化 `H264Decoder`
- 收到 `MSG_H264_CHUNK` 时喂给解码器
- 解码线程读取 RGB 帧 → `QImage` → 信号更新显示
- JPEG 模式保持兼容

## ffmpeg 关键参数

### 服务端编码（以 NVENC 为例）
```
ffmpeg -f rawvideo -pix_fmt rgb24 -s 2160x1440 -r 30 -i pipe:0 \
  -c:v h264_nvenc -preset p1 -tune ll -zerolatency 1 \
  -rc cbr -b:v 4M -bufsize 500k \
  -g 30 -bf 0 -bsf:v dump_extra \
  -f h264 pipe:1
```

### 客户端解码
```
ffmpeg -f h264 -i pipe:0 \
  -c:v h264_v4l2m2m \
  -f rawvideo -pix_fmt rgb24 -s 2160x1440 \
  pipe:1
```

## 实现步骤

1. 新建 `server/h264_encoder.py` — 编码器管理（自动检测最佳硬件编码器）
2. 新建 `client/h264_decoder.py` — 解码器管理（自动检测硬件解码器）
3. 修改 `common/protocol.py` — 新增消息类型
4. 修改 `server/main.py` — 添加 `--h264` 模式
5. 修改 `client/main.py` — 处理 H.264 流
6. 端到端测试
7. 提交

## 验证

1. 服务端 `--h264` 模式启动，确认使用了 NVENC 编码器
2. 客户端连接后画面正常显示
3. 对比带宽：JPEG 模式 vs H.264 模式的 Mbps 输出
4. 检查延迟是否可接受（目标 <100ms）
5. 回退测试：不加 `--h264` 仍用 JPEG 模式正常工作
