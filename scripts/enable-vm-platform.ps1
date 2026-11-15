# 启用 Windows 虚拟机平台 + WSL（Docker Desktop 依赖）
# 需要管理员权限运行（UAC 弹窗）
Write-Host "== 1/3 启用 VirtualMachinePlatform 功能（约 1-2 分钟）=="
dism /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart

Write-Host "== 2/3 启用 Microsoft-Windows-Subsystem-Linux 功能 =="
dism /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart

Write-Host "== 3/3 设置 hypervisor 开机自启 =="
bcdedit /set hypervisorlaunchtype auto

Write-Host ""
Write-Host "== 全部完成。请重启电脑，然后启动 Docker Desktop =="
Read-Host "按回车关闭此窗口"
