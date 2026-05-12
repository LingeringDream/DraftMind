$daemonJson = "$env:USERPROFILE\.docker\daemon.json"
$json = '{"registry-mirrors":["https://docker.1ms.run","https://docker.xuanyuan.me","https://docker.m.daocloud.io","https://huecker.io","https://dockerhub.timeweb.cloud"]}'

if (Test-Path $daemonJson) {
    $raw = Get-Content $daemonJson -Raw
    if ($raw -match "registry-mirrors") {
        Write-Host "[INFO] Mirrors already configured, updating..." -ForegroundColor Yellow
    }
    Copy-Item $daemonJson "$daemonJson.bak" -Force
}

$dir = Split-Path $daemonJson -Parent
New-Item -ItemType Directory -Path $dir -Force | Out-Null
$json | Set-Content $daemonJson -Encoding UTF8
Write-Host "[INFO] Written to $daemonJson" -ForegroundColor Green

Write-Host "[INFO] Restarting Docker Desktop..." -ForegroundColor Green
Get-Process "Docker Desktop" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 5
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
Start-Sleep -Seconds 20
Write-Host "[INFO] Done" -ForegroundColor Green
