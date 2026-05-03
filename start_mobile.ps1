# divAI Mobile Dispatch Launcher — HTTPS edition
$pythonPath = "python"
$root = $PSScriptRoot

Write-Host "`n[divAI] Checking dependencies..." -ForegroundColor Cyan
& $pythonPath -m pip install fastapi uvicorn python-multipart cryptography --quiet

Write-Host "[divAI] Generating SSL certificate..." -ForegroundColor Cyan
& $pythonPath "$root\gen_cert.py"

# Get local IP for display
$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
    $_.InterfaceAlias -notlike "*Loopback*" -and $_.IPAddress -notlike "169.*"
} | Select-Object -First 1).IPAddress

Write-Host ""
Write-Host "  divAI Mobile running at:" -ForegroundColor White
Write-Host "  https://$($ip):8443" -ForegroundColor Cyan
Write-Host ""
Write-Host "  (If first time: AirDrop divai.crt to iPhone and trust it in Settings)" -ForegroundColor DarkGray
Write-Host ""

& $pythonPath -m uvicorn div_server:app --host 0.0.0.0 --port 8443 --ssl-keyfile "$root\divai.key" --ssl-certfile "$root\divai.crt" --reload
