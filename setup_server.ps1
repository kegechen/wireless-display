#!/usr/bin/env pwsh
# Windows 服务端依赖安装脚本
# 用法: .\setup_server.ps1

Write-Host "=== Wireless Display Server Setup (Windows) ===" -ForegroundColor Cyan
Write-Host ""

# 检查 Python
Write-Host "[1/4] 检查 Python ..." -ForegroundColor Yellow
try {
    $pyVer = python --version 2>&1
    Write-Host "  OK: $pyVer" -ForegroundColor Green
} catch {
    Write-Host "  ERROR: 未找到 Python，请先安装 Python 3.8+" -ForegroundColor Red
    exit 1
}

# 安装 Python 依赖
Write-Host "[2/4] 安装 Python 依赖 ..." -ForegroundColor Yellow
pip install mss Pillow
Write-Host ""

Write-Host "[3/4] 安装可选加速依赖 ..." -ForegroundColor Yellow
Write-Host "  dxcam (GPU 屏幕捕获) ..."
pip install dxcam 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  dxcam 安装失败（可选，将使用 CPU 捕获）" -ForegroundColor DarkYellow
}
Write-Host "  PyTurboJPEG (SIMD JPEG 编码) ..."
pip install PyTurboJPEG 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  PyTurboJPEG 安装失败（可选，将使用 Pillow 编码）" -ForegroundColor DarkYellow
}
Write-Host ""

# 检查 ffmpeg（H.264 模式需要）
Write-Host "[4/4] 检查 ffmpeg (H.264 模式需要) ..." -ForegroundColor Yellow
$ffmpegPath = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ffmpegPath) {
    $ffVer = ffmpeg -version 2>&1 | Select-Object -First 1
    Write-Host "  OK: $ffVer" -ForegroundColor Green
} else {
    Write-Host "  WARNING: 未找到 ffmpeg" -ForegroundColor DarkYellow
    Write-Host "  H.264 模式需要 ffmpeg，安装方法:" -ForegroundColor DarkYellow
    Write-Host "    winget install Gyan.FFmpeg" -ForegroundColor White
    Write-Host "    或从 https://www.gyan.dev/ffmpeg/builds/ 下载" -ForegroundColor White
    Write-Host "  不安装 ffmpeg 仍可使用 JPEG 模式" -ForegroundColor DarkYellow
}

Write-Host ""
Write-Host "=== 安装完成 ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "启动命令:" -ForegroundColor Yellow
Write-Host "  JPEG 模式:  python server/main.py --monitor 2" -ForegroundColor White
Write-Host "  H.264 模式: python server/main.py --monitor 2 --h264" -ForegroundColor White
Write-Host "  查看显示器: python server/main.py --list-monitors" -ForegroundColor White
Write-Host ""
