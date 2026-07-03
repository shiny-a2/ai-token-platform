# AI Token Platform — boot orchestrator.
# Starts the cloudflared quick tunnel, waits for its (new) public URL,
# writes PUBLIC_URL into .env, then starts the server (which re-sets the
# Telegram mini-app menu button from PUBLIC_URL on startup).
# Registered as a Scheduled Task so everything survives a reboot.

$ErrorActionPreference = "Continue"
$Root   = "C:\A2\ai-token-platform"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Cfd    = Join-Path $Root "tools\cloudflared.exe"
$EnvFile = Join-Path $Root ".env"
$TunnelLog = Join-Path $Root "data\tunnel.log"

# ---- 1) stop leftovers ----
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
$conn = Get-NetTCPConnection -LocalPort 8095 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

# ---- 2) start tunnel (http2: QUIC/UDP is blocked on this host) ----
Remove-Item $TunnelLog -ErrorAction SilentlyContinue
Start-Process -FilePath $Cfd -ArgumentList "tunnel","--url","http://127.0.0.1:8095","--protocol","http2" `
  -WorkingDirectory $Root -WindowStyle Hidden `
  -RedirectStandardError $TunnelLog -RedirectStandardOutput (Join-Path $Root "data\tunnel.out.log")

# ---- 3) wait for the public URL (max ~60s) ----
$url = $null
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    if (Test-Path $TunnelLog) {
        $m = Select-String -Path $TunnelLog -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -ErrorAction SilentlyContinue |
             Select-Object -First 1
        if ($m) { $url = $m.Matches[0].Value; break }
    }
}

# ---- 4) write PUBLIC_URL into .env ----
if ($url) {
    $content = Get-Content $EnvFile -Raw -Encoding UTF8
    $content = $content -replace "PUBLIC_URL=.*", "PUBLIC_URL=$url"
    Set-Content -Path $EnvFile -Value $content -Encoding utf8 -NoNewline
}

# ---- 5) start the server (reads .env fresh; sets the menu button itself) ----
Start-Process -FilePath $Python -ArgumentList "run.py" -WorkingDirectory $Root -WindowStyle Hidden `
  -RedirectStandardOutput (Join-Path $Root "data\server.out.log") `
  -RedirectStandardError (Join-Path $Root "data\server.err.log")

"started: tunnel=$url" | Out-File (Join-Path $Root "data\start_all.log") -Encoding utf8
