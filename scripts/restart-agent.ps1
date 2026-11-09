param([switch]$KeepAlive)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'python-agent\.venv\Scripts\python.exe'
$logs = Join-Path $root 'logs'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
. (Join-Path $PSScriptRoot 'python-tracing.ps1')
Set-PythonTracingEnvironment
$guardInfo = New-Object System.Diagnostics.ProcessStartInfo
$guardInfo.FileName = $python
$guardInfo.Arguments = '"' + (Join-Path $root 'scripts\agent-restart-guard.py') + '"'
$guardInfo.WorkingDirectory = $root
$guardInfo.UseShellExecute = $false
$guardInfo.CreateNoWindow = $true
$guardInfo.RedirectStandardInput = $true
$guardInfo.RedirectStandardOutput = $true
$guardInfo.RedirectStandardError = $true
$guard = New-Object System.Diagnostics.Process
$guard.StartInfo = $guardInfo
$started = $null
$healthy = $false
$guardStarted = $false
try {
    $guardStarted = $guard.Start()
    if (!$guardStarted) { throw 'Could not acquire restart guard; Agent was not stopped.' }
    $ready = $guard.StandardOutput.ReadLineAsync()
    if (!$ready.Wait(15000)) { throw 'Restart guard timed out; Agent was not stopped.' }
    $guardReply = $ready.Result | ConvertFrom-Json
    if (!$guardReply -or $guardReply.status -ne 'ready') {
        throw 'Agent has active requests or its idle state could not be verified; restart refused.'
    }
    if ($guard.HasExited) { throw 'Restart guard lost; Agent was not stopped.' }
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
    if ($guard.HasExited) { throw 'Restart guard lost; refusing to stop Agent.' }
    # Stopping the child can also terminate its venv launcher. Treat that race
    # as an already completed stop, while still surfacing real stop failures.
    try { Stop-Process -Id $process.ProcessId -Force }
    catch {
        if (Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue) { throw }
    }
}
$previousAgentRuntime=$env:EASYJOB_AGENT_RUNTIME
try {
    $env:EASYJOB_AGENT_RUNTIME='true'
    $started = Start-Process -FilePath $python -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000') `
        -WorkingDirectory (Join-Path $root 'python-agent') -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logs 'python-context-128k.out.log') `
        -RedirectStandardError (Join-Path $logs 'python-context-128k.err.log') -PassThru
} finally { $env:EASYJOB_AGENT_RUNTIME=$previousAgentRuntime }
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Seconds 2
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 2
        if ($health.status -eq 'ok') {
            Write-Host "Agent HTTP ready (launcher PID $($started.Id)); checking Java -> Agent RPC."
            if ($guard.HasExited) { throw 'Restart guard lost during startup.' }
            & $python (Join-Path $root 'scripts\agent-rpc-ready.py') --timeout 25
            if ($LASTEXITCODE -ne 0) { throw 'Java -> Agent RPC did not recover.' }
            if ($guard.HasExited) { throw 'Restart guard lost during RPC warmup.' }
            $healthy = $true
            Write-Host 'Agent restarted; HTTP and Java -> Agent RPC are ready.'
            Get-Content -LiteralPath (Join-Path $logs 'python-context-128k.out.log') |
                Select-String -Pattern 'Agent Token budgets:'
            break
        }
    } catch {
        # HTTP startup may still be in progress. Once HTTP is ready, a failed
        # cross-service check must not be silently reported as restart success.
        if ($health -and $health.status -eq 'ok') { throw }
    }
}
if (!$healthy) { throw 'Agent did not become healthy; inspect logs/python-context-128k.err.log.' }
} finally {
    # Release admission before KeepAlive waits for the service lifetime.
    if ($guardStarted -and !$guard.HasExited) {
        try { $guard.StandardInput.WriteLine('release'); $guard.StandardInput.Close() } catch { }
        if (!$guard.WaitForExit(5000)) { $guard.Kill(); $guard.WaitForExit() }
    }
    $guard.Dispose()
}
if ($KeepAlive -and $healthy) { $started.WaitForExit() }
