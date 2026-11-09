param([switch]$KeepAlive,[string]$ValidatedJar)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'java-tracing.ps1')
[string[]]$javaTracingArguments = @(Get-JavaTracingArguments -ProjectRoot $root -ServiceName 'easyjob-auth')
$java='D:\jdk\bin\java.exe'
$jar=Join-Path $root 'auth-service\target\easyjob-auth-0.0.1-SNAPSHOT.jar'
if($ValidatedJar){$replacement=[IO.Path]::GetFullPath((Join-Path $root $ValidatedJar));if(!$replacement.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)-or !(Test-Path -LiteralPath $replacement)-or [IO.Path]::GetFileName($replacement)-ne 'easyjob-auth-0.0.1-SNAPSHOT.jar'){throw 'Unverified Auth build path.'}}
if (!(Test-Path -LiteralPath $jar)) { throw 'Build auth-service before restart.' }
$targets=@(Get-CimInstance Win32_Process -Filter "Name='java.exe'" | Where-Object { $_.ExecutablePath -eq $java -and $_.CommandLine -match 'auth-service\\target\\easyjob-auth-0.0.1-SNAPSHOT.jar' -and $_.CommandLine -match 'file:./temp/auth-runtime.yml' })
$listeners=@(Get-NetTCPConnection -LocalPort 8081 -State Listen -ErrorAction SilentlyContinue)
if (@($listeners|Where-Object { $_.OwningProcess -notin @($targets.ProcessId) }).Count) { throw 'Port 8081 has an unverified owner.' }
foreach($process in $targets){Stop-Process -Id $process.ProcessId -Force}
if($ValidatedJar){Copy-Item -LiteralPath $replacement -Destination $jar -Force}
$started=Start-Process -FilePath $java -ArgumentList ($javaTracingArguments + @('-jar','auth-service\target\easyjob-auth-0.0.1-SNAPSHOT.jar','--spring.profiles.include=tracing','--spring.config.additional-location=file:./temp/auth-runtime.yml')) -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $root 'logs/auth.out.log') -RedirectStandardError (Join-Path $root 'logs/auth.err.log') -PassThru
for($attempt=0;$attempt -lt 30;$attempt++) {
    Start-Sleep -Seconds 2
    try { $r=Invoke-RestMethod 'http://127.0.0.1:8081/actuator/health' -TimeoutSec 2;if($r.status -eq 'UP'){Write-Output "Auth service ready (PID $($started.Id)).";if($KeepAlive){$started.WaitForExit()};exit 0} } catch {}
    if($started.HasExited){throw 'Auth service exited; inspect logs/auth.err.log.'}
}
throw 'Auth service did not become ready.'
