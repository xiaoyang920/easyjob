param([switch]$KeepAlive)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'python-agent\.venv\Scripts\python.exe'
$logs = Join-Path $root 'logs'
$agentProcesses = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'")
$launchers = @($agentProcesses | Where-Object {
    $_.ExecutablePath -eq $python -and $_.CommandLine -match '-m uvicorn app.main:app --host 127.0.0.1 --port 8000'
})
$children = @($agentProcesses | Where-Object {
    $_.ParentProcessId -in @($launchers.ProcessId) -and
    $_.CommandLine -match '-m uvicorn app.main:app --host 127.0.0.1 --port 8000'
})
$targets = @($children) + @($launchers)
$listeners = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
if (@($listeners | Where-Object { $_.OwningProcess -notin @($targets.ProcessId) }).Count) {
    throw 'Port 8000 belongs to an unverified process; refusing to stop it.'
}
foreach ($process in $targets) {
    Stop-Process -Id $process.ProcessId -Force
}
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$started = Start-Process -FilePath $python -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000') `
    -WorkingDirectory (Join-Path $root 'python-agent') -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logs 'python-context-128k.out.log') `
    -RedirectStandardError (Join-Path $logs 'python-context-128k.err.log') -PassThru
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Seconds 2
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 2
        if ($health.status -eq 'ok') {
            Write-Host "Agent restarted and healthy (launcher PID $($started.Id))."
            Get-Content -LiteralPath (Join-Path $logs 'python-context-128k.out.log') |
                Select-String -Pattern 'Agent Token budgets:'
            if ($KeepAlive) { $started.WaitForExit() }
            exit 0
        }
    } catch { }
}
throw 'Agent did not become healthy; inspect logs/python-context-128k.err.log.'
