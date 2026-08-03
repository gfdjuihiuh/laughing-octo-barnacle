# 新闻之眼 · 注册每日定时任务
# 以管理员身份运行此脚本：
#   powershell -ExecutionPolicy Bypass -File scripts\install_schedule.ps1

$TaskName = "eyes-daily"
$ScriptPath = "C:\Users\Blue\Desktop\git\scripts\run_daily.cmd"
$StartTime = "23:30"

Write-Host "正在注册计划任务 '$TaskName' 每日 $StartTime 运行..." -ForegroundColor Cyan

# 先删除旧任务（如果存在）
schtasks /Delete /TN $TaskName /F 2>$null

# 创建新任务
schtasks /Create /F `
    /TN $TaskName `
    /TR "$ScriptPath" `
    /SC DAILY `
    /ST $StartTime `
    /RL HIGHEST

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ 任务注册成功！每天 $StartTime 自动运行" -ForegroundColor Green
    Write-Host "  查看任务: schtasks /Query /TN $TaskName" -ForegroundColor Gray
    Write-Host "  手动运行: schtasks /Run /TN $TaskName" -ForegroundColor Gray
    Write-Host "  删除任务: schtasks /Delete /TN $TaskName /F" -ForegroundColor Gray
} else {
    Write-Host "✗ 任务注册失败，请以管理员身份运行此脚本" -ForegroundColor Red
}
