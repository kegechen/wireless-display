#!/usr/bin/env pwsh
# Windows 服务端启动脚本
# 用法:
#   .\start_server.ps1                      # JPEG 模式，自动检测虚拟副屏
#   .\start_server.ps1 -H264                # H.264 模式
#   .\start_server.ps1 -Monitor 3           # 指定显示器
#   .\start_server.ps1 -H264 -Bitrate 6M    # H.264 + 自定义码率
#   .\start_server.ps1 -ListMonitors        # 列出显示器

param(
    [int]$Monitor = 0,
    [int]$Fps = 30,
    [int]$Quality = 70,
    [switch]$H264,
    [string]$Bitrate = "4M",
    [string]$Encoder = "auto",
    [switch]$Cpu,
    [switch]$VirtualDisplay,
    [switch]$ListMonitors,
    [string]$Host_ = "0.0.0.0",
    [int]$Port = 9876
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# 列出显示器
if ($ListMonitors) {
    python server/main.py --list-monitors
    exit 0
}

# 自动检测显示器
if ($Monitor -eq 0) {
    Write-Host "未指定显示器，列出可用显示器:" -ForegroundColor Yellow
    python server/main.py --list-monitors
    Write-Host ""
    $Monitor = Read-Host "请输入要捕获的显示器编号"
    if (-not $Monitor) {
        Write-Host "已取消" -ForegroundColor Red
        exit 1
    }
}

# 构建参数
$args_ = @(
    "server/main.py",
    "--host", $Host_,
    "--port", $Port,
    "--monitor", $Monitor,
    "--fps", $Fps
)

if ($H264) {
    $args_ += "--h264"
    $args_ += "--bitrate"
    $args_ += $Bitrate
    $args_ += "--encoder"
    $args_ += $Encoder
    Write-Host "模式: H.264 (bitrate=$Bitrate, encoder=$Encoder)" -ForegroundColor Cyan
} else {
    $args_ += "--quality"
    $args_ += $Quality
    Write-Host "模式: JPEG (quality=$Quality)" -ForegroundColor Cyan
}

if ($Cpu) {
    $args_ += "--cpu"
}

if ($VirtualDisplay) {
    $args_ += "--virtual-display"
}

Write-Host "启动服务端: python $($args_ -join ' ')" -ForegroundColor Green
Write-Host ""

python @args_
