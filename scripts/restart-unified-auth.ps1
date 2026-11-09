param([switch]$KeepAlive)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$python=Join-Path $root 'python-agent\.venv\Scripts\python.exe'
$java=Join-Path $root 'target\unified-auth-build\easyjob-0.0.1-SNAPSHOT.jar'
$auth=Join-Path $root 'auth-service\target\validated-build\easyjob-auth-0.0.1-SNAPSHOT.jar'
$gateway=Join-Path $root 'gateway\target\validated-build\easyjob-gateway-0.0.1-SNAPSHOT.jar'
foreach($artifact in @($java,$auth,$gateway)){if(!(Test-Path -LiteralPath $artifact -PathType Leaf)){throw 'Build and validate all three services before unified restart.'}}
$info=New-Object Diagnostics.ProcessStartInfo
$info.FileName=$python
$info.Arguments='"'+(Join-Path $root 'scripts\agent-restart-guard.py')+'" --hold-seconds 240'
$info.WorkingDirectory=$root
$info.UseShellExecute=$false
$info.CreateNoWindow=$true
$info.RedirectStandardInput=$true
$info.RedirectStandardOutput=$true
$info.RedirectStandardError=$true
$guard=New-Object Diagnostics.Process
$guard.StartInfo=$info
$env:PYTHONUTF8='1'
. (Join-Path $PSScriptRoot 'python-tracing.ps1')
Set-PythonTracingEnvironment
function Invoke-Restart([string]$name,[string]$script,[string]$artifact){
    & (Join-Path $root $script) -ValidatedJar $artifact
    if($LASTEXITCODE -ne 0){throw "$name restart failed; inspect its restart log."}
    if($guard.HasExited){throw 'Restart guard lost.'}
    Write-Output "$name restarted and ready."
}
try {
    if(!$guard.Start()){throw 'Could not acquire restart admission guard.'}
    $ready=$guard.StandardOutput.ReadLineAsync()
    if(!$ready.Wait(15000)-or ($ready.Result|ConvertFrom-Json).status-ne 'ready'-or $guard.HasExited){throw 'Active Agent work or unavailable admission guard; no service stopped.'}
    Invoke-Restart 'auth' 'scripts/restart-auth.ps1' 'auth-service/target/validated-build/easyjob-auth-0.0.1-SNAPSHOT.jar'
    Invoke-Restart 'blog' 'scripts/restart-java.ps1' 'target/unified-auth-build/easyjob-0.0.1-SNAPSHOT.jar'
    $processes=@(Get-CimInstance Win32_Process -Filter "Name='python.exe'")
    $launchers=@($processes|Where-Object {$_.ExecutablePath-eq $python-and $_.CommandLine-match '-m uvicorn app.main:app --host 127.0.0.1 --port 8000'})
    $children=@($processes|Where-Object {$_.ParentProcessId-in @($launchers.ProcessId)-and $_.CommandLine-match '-m uvicorn app.main:app --host 127.0.0.1 --port 8000'})
    $targets=@($children)+@($launchers)
    $listeners=@(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
    if(@($listeners|Where-Object {$_.OwningProcess-notin @($targets.ProcessId)}).Count){throw 'Agent port has an unverified owner.'}
    foreach($process in $targets){if($guard.HasExited){throw 'Restart guard lost.'};try{Stop-Process -Id $process.ProcessId -Force}catch{if(Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue){throw}}}
    $previousAgentRuntime=$env:EASYJOB_AGENT_RUNTIME
    try {
        $env:EASYJOB_AGENT_RUNTIME='true'
        $agent=Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000') -WorkingDirectory (Join-Path $root 'python-agent') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $root 'logs/python-auth.out.log') -RedirectStandardError (Join-Path $root 'logs/python-auth.err.log') -PassThru
    } finally { $env:EASYJOB_AGENT_RUNTIME=$previousAgentRuntime }
    $healthy=$false
    for($attempt=0;$attempt-lt 35;$attempt++){
        Start-Sleep -Seconds 2
        if($guard.HasExited-or $agent.HasExited){throw 'Restart guard or Agent lost during startup.'}
        try{if((Invoke-RestMethod 'http://127.0.0.1:8000/health/ready' -TimeoutSec 2).status-eq 'ready'){$healthy=$true;break}}catch{}
    }
    if(!$healthy){throw 'Agent readiness failed.'}
    Invoke-Restart 'gateway' 'scripts/restart-gateway.ps1' 'gateway/target/validated-build/easyjob-gateway-0.0.1-SNAPSHOT.jar'
    & $python (Join-Path $root 'scripts\agent-rpc-ready.py') --timeout 25
    if($LASTEXITCODE-ne 0){throw 'Java -> Agent readiness failed.'}
    Write-Output 'Unified Auth, Blog, Gateway and Agent are ready.'
} finally {
    if(!$guard.HasExited){try{$guard.StandardInput.WriteLine('release');$guard.StandardInput.Close()}catch{};if(!$guard.WaitForExit(5000)){$guard.Kill()}}
    $guard.Dispose()
}
if($KeepAlive){while($true){Start-Sleep -Seconds 30}}
