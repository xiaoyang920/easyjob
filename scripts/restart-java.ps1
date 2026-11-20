param([switch]$KeepAlive, [switch]$Build, [string]$ValidatedJar)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'java-tracing.ps1')
[string[]]$javaTracingArguments = @(Get-JavaTracingArguments -ProjectRoot $root -ServiceName 'easyjob-blog')
$java = 'D:\jdk\bin\java.exe'
$jar = 'services\blog-service\target\easyjob-0.0.1-SNAPSHOT.jar'
$runtimeArgument = '--spring.config.additional-location=file:./temp/application-runtime.yml'
if (Test-Path -LiteralPath (Join-Path $root 'temp\search-index-blog.yml')) {
    $runtimeArgument += ',file:./temp/search-index-blog.yml'
}
if (Test-Path -LiteralPath (Join-Path $root 'temp\excel-runtime.yml')) {
    $runtimeArgument += ',file:./temp/excel-runtime.yml'
}
if ($ValidatedJar) {
    if ($Build) { throw 'Use Build or ValidatedJar, not both.' }
    $validatedPath = [IO.Path]::GetFullPath((Join-Path $root $ValidatedJar))
    if (!$validatedPath.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase) -or
        !(Test-Path -LiteralPath $validatedPath -PathType Leaf) -or
        [IO.Path]::GetFileName($validatedPath) -ne 'easyjob-0.0.1-SNAPSHOT.jar') { throw 'Validated JAR must be an existing workspace build artifact.' }
}
$targets = @(Get-CimInstance Win32_Process -Filter "Name='java.exe'" | Where-Object {
    $_.ExecutablePath -eq $java -and
    $_.CommandLine -match '-jar (?:(?:services[\\/])?blog-service[\\/])?target[\\/]easyjob-0\.0\.1-SNAPSHOT\.jar(?:\s|$)' -and
    $_.CommandLine -match '--spring.config.additional-location=file:./temp/application-runtime.yml'
})
$listeners = @(Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalAddress -eq '127.0.0.1' })
if (@($listeners | Where-Object { $_.OwningProcess -notin @($targets.ProcessId) }).Count) {
    throw 'Port 8080 belongs to an unverified process.'
}
foreach ($process in $targets) { Stop-Process -Id $process.ProcessId -Force }
if ($ValidatedJar) {
    New-Item -ItemType Directory -Path (Join-Path $root 'services\blog-service\target') -Force | Out-Null
    Copy-Item -LiteralPath $validatedPath -Destination (Join-Path $root $jar) -Force
}
if ($Build) {
    $env:JAVA_HOME = 'D:\jdk'
    Push-Location -LiteralPath (Join-Path $root 'services/blog-service')
    try {
        & 'D:\IntelliJ IDEA Community Edition 2025.1.3\plugins\maven\lib\maven3\bin\mvn.cmd' -q -DskipTests package
        if ($LASTEXITCODE -ne 0) { throw 'Java package failed; service not restarted.' }
    } finally { Pop-Location }
}
$started = Start-Process -FilePath $java -ArgumentList ($javaTracingArguments + @('-jar', $jar, '--server.address=127.0.0.1', '--spring.profiles.include=tracing', $runtimeArgument)) `
    -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $root 'logs/java.out.log') `
    -RedirectStandardError (Join-Path $root 'logs/java.err.log') -PassThru
for ($attempt = 0; $attempt -lt 25; $attempt++) {
    Start-Sleep -Seconds 2
    try {
        $result = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/actuator/health' -TimeoutSec 2
        if ($result.status -eq 'UP') {
            Write-Host "Java restarted and healthy (PID $($started.Id))."
            if ($KeepAlive) { $started.WaitForExit() }
            exit 0
        }
    } catch { }
}
throw 'Java did not become healthy; inspect logs/java.err.log.'
