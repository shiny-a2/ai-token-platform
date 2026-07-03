# AI Token Platform — boot orchestrator.
# Starts Caddy (stable HTTPS on 8443 with auto-renewing certificate) and the
# app server. PUBLIC_URL in .env is STATIC now — the address survives reboots.
# Registered as the Scheduled Task "AITokenPlatform".

$ErrorActionPreference = "Continue"
$Root   = "C:\A2\ai-token-platform"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Caddy  = Join-Path $Root "tools\caddy.exe"

# ---- 1) stop leftovers ----
Get-Process caddy -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
$conn = Get-NetTCPConnection -LocalPort 8095 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

# ---- 2) start Caddy (HTTPS reverse proxy, cert auto-managed) ----
Start-Process -FilePath $Caddy -ArgumentList "run","--config",(Join-Path $Root "data\Caddyfile") `
  -WorkingDirectory $Root -WindowStyle Hidden `
  -RedirectStandardError (Join-Path $Root "data\caddy.log") `
  -RedirectStandardOutput (Join-Path $Root "data\caddy.out.log")

# ---- 3) start the app server (bot + dashboard + mini app API) ----
Start-Process -FilePath $Python -ArgumentList "run.py" -WorkingDirectory $Root -WindowStyle Hidden `
  -RedirectStandardOutput (Join-Path $Root "data\server.out.log") `
  -RedirectStandardError (Join-Path $Root "data\server.err.log")

"started $(Get-Date -Format s)" | Out-File (Join-Path $Root "data\start_all.log") -Encoding utf8
