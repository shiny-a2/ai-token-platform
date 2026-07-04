# AI Token Platform — restart helper.
# The platform runs as two real Windows SERVICES (installed via WinSW,
# see tools/svc/): they auto-start at boot and auto-restart on crash.
#   AITokenPlatform-App    python run.py       (bot + dashboard + mini app, :8095)
#   AITokenPlatform-Caddy  caddy run           (public HTTPS, :8443)
# This script just restarts them (e.g. after a code or .env change).

$ErrorActionPreference = "Continue"

Restart-Service -Name "AITokenPlatform-App" -Force
Restart-Service -Name "AITokenPlatform-Caddy" -Force

Get-Service AITokenPlatform-* | Select-Object Name, Status, StartType
