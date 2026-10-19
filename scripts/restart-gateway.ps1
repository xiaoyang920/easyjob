param([switch]$Build, [string]$ValidatedJar, [switch]$KeepAlive)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$java='D:\jdk\bin\java.exe'
$destination=Join-Path $root 'gateway\target\easyjob-gateway-0.0.1-SNAPSHOT.jar'
if ($Build -and $ValidatedJar) {throw 'Choose Build or ValidatedJar.'}
if ($Build) {
    $env:JAVA_HOME='D:\jdk'
    Push-Location $root
    try {
        & 'D:\IntelliJ IDEA Community Edition 2025.1.3\plugins\maven\lib\maven3\bin\mvn.cmd' -B -f gateway/pom.xml '-Deasyjob.build.directory=target/restart-build' '-DskipTests' package
        if ($LASTEXITCODE -ne 0) {throw 'Gateway build failed; running service preserved.'}
        $ValidatedJar='gateway/target/restart-build/easyjob-gateway-0.0.1-SNAPSHOT.jar'
    } finally {Pop-Location}
}
if ($ValidatedJar) {
    $replacement=[IO.Path]::GetFullPath((Join-Path $root $ValidatedJar))
    if (!$replacement.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase) -or
        !(Test-Path -LiteralPath $replacement -PathType Leaf) -or
        [IO.Path]::GetFileName($replacement) -ne 'easyjob-gateway-0.0.1-SNAPSHOT.jar') {throw 'Unverified gateway build path.'}
}
$targets=@(Get-CimInstance Win32_Process -Filter "Name='java.exe'" | Where-Object {
    $_.ExecutablePath -eq $java -and $_.CommandLine -match '-jar gateway\\target\\easyjob-gateway-0.0.1-SNAPSHOT.jar' -and
    $_.CommandLine -match '--spring.config.additional-location=file:./temp/gateway-runtime.yml'
})
$listeners=@(Get-NetTCPConnection -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue)
if (@($listeners | Where-Object {$_.OwningProcess -notin @($targets.ProcessId)}).Count) {throw 'Port 8090 belongs to an unverified process.'}
foreach ($process in $targets) {Stop-Process -Id $process.ProcessId -Force}
if ($ValidatedJar) {Copy-Item -LiteralPath $replacement -Destination $destination -Force}
$started=Start-Process -FilePath $java -ArgumentList @('-jar','gateway\target\easyjob-gateway-0.0.1-SNAPSHOT.jar','--spring.config.additional-location=file:./temp/gateway-runtime.yml') -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $root 'logs/gateway.out.log') -RedirectStandardError (Join-Path $root 'logs/gateway.err.log') -PassThru
for ($attempt=0;$attempt -lt 20;$attempt++) {
    Start-Sleep -Seconds 2
    try {
        $reply=Invoke-RestMethod 'http://127.0.0.1:8090/api/article/list' -TimeoutSec 2
        if ($reply.code -eq 200) {
            Write-Host "Gateway restarted and healthy (PID $($started.Id))."
            if ($KeepAlive) { $started.WaitForExit() }
            exit 0
        }
    } catch {}
}
throw 'Gateway not ready; inspect logs/gateway.*.log.'
