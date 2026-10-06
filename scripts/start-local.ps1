param(
    [switch]$KeepAlive,
    [switch]$Build,
    [switch]$Reindex,
    [string]$JavaHome = 'D:\jdk',
    [string]$Maven = 'D:\IntelliJ IDEA Community Edition 2025.1.3\plugins\maven\lib\maven3\bin\mvn.cmd',
    [string]$Node = 'D:\applications\nodejs\node.exe',
    [string]$ElasticsearchHome = 'D:\applications\ES\elasticsearch-9.2.4-windows-x86_64\elasticsearch-9.2.4',
    [string]$RabbitHome = 'D:\applications\rabbitmq\rabbitmq_server-4.1.8'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$logs = Join-Path $root 'logs'
$python = Join-Path $root 'python-agent\.venv\Scripts\python.exe'
$docker = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
$image = 'redis/redis-stack@sha256:5d5154123426693540ea6c1d9e638eae2bf2024879c839db6fcfdd7717e817c7'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
Set-Location -LiteralPath $root
$env:JAVA_HOME = $JavaHome
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

function Test-Port([int]$Port) {
    $client = [Net.Sockets.TcpClient]::new()
    try {
        $pending = $client.ConnectAsync('127.0.0.1', $Port)
        return $pending.Wait(500) -and $client.Connected
    } catch { return $false } finally { $client.Dispose() }
}

function Wait-Port([int]$Port) {
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        if (Test-Port $Port) { return }
        Start-Sleep -Seconds 1
    }
    throw "Port $Port did not start; inspect $logs"
}

function Start-Hidden([string]$Name, [string]$File, [string[]]$Arguments, [string]$Directory) {
    $process = Start-Process -FilePath $File -ArgumentList $Arguments -WorkingDirectory $Directory `
        -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs "$Name.out.log") `
        -RedirectStandardError (Join-Path $logs "$Name.err.log") -PassThru
    Write-Host "$Name launched (PID $($process.Id))"
}

if (!(Test-Path (Join-Path $root 'temp/application-runtime.yml'))) {
    throw 'Missing local runtime config. Run scripts/prepare-local.py with the project Python environment first.'
}
if (!(Test-Port 3306)) { throw 'MySQL must be running on 3306 before starting the project.' }
if ($Reindex -and (Test-Port 8080)) { throw 'Stop the existing project Java process before requesting -Reindex.' }
if ($Build -and (Test-Port 8080)) { throw 'Stop the existing project Java process before rebuilding its JAR.' }
if ($Build) {
    & $Maven -DskipTests package *> (Join-Path $logs 'maven-package.log')
    if ($LASTEXITCODE -ne 0) { throw 'Java build failed; inspect logs/maven-package.log' }
}

function Test-Docker {
    # Windows PowerShell 5 treats native stderr as a terminating error under Stop.
    # A stopped daemon is an expected condition here, followed by starting Desktop.
    $ErrorActionPreference = 'Continue'
    & $docker info --format '{{.ServerVersion}}' *> $null
    return $LASTEXITCODE -eq 0
}

if (!(Test-Docker)) {
    Start-Process -FilePath 'C:\Program Files\Docker\Docker\Docker Desktop.exe' -WindowStyle Hidden
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        if (Test-Docker) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if (!$ready) { throw 'Docker Desktop did not become ready.' }
}
if (!(Test-Port 6379)) {
    $existing = @(& $docker ps -a --format '{{.Names}}')
    if ($existing -contains 'redis-stack') {
        & $docker start redis-stack | Out-Null
    } elseif ($existing -contains 'easyjob-cache-redis') {
        & $docker start easyjob-cache-redis | Out-Null
    } else {
        & $docker run -d --name easyjob-cache-redis --restart unless-stopped `
            -p 127.0.0.1:6379:6379 -v easyjob-cache-data:/data $image | Out-Null
    }
    if ($LASTEXITCODE -ne 0) { throw 'Cache Redis failed to start.' }
    Wait-Port 6379
}
if (!(Test-Port 6380)) {
    $existing = @(& $docker ps -a --format '{{.Names}}')
    if ($existing -contains 'easyjob-checkpoint-redis') {
        & $docker start easyjob-checkpoint-redis | Out-Null
    } else {
        & $docker run -d --name easyjob-checkpoint-redis --restart unless-stopped `
            -p 127.0.0.1:6380:6379 -v easyjob-checkpoint-data:/data --entrypoint redis-server $image `
            --dir /data --appendonly yes --protected-mode no `
            --loadmodule /opt/redis-stack/lib/redisearch.so --loadmodule /opt/redis-stack/lib/rejson.so | Out-Null
    }
    if ($LASTEXITCODE -ne 0) { throw 'Checkpoint Redis failed to start.' }
    Wait-Port 6380
}
if (!(Test-Port 9200)) {
    $env:ES_JAVA_HOME = $JavaHome
    $env:ES_JAVA_OPTS = '-Xms1g -Xmx1g'
    Start-Hidden 'elasticsearch' "$env:WINDIR\System32\cmd.exe" @('/c', "`"$ElasticsearchHome\bin\elasticsearch.bat`"") $ElasticsearchHome
    Wait-Port 9200
}
if (!(Test-Port 5672)) {
    Start-Hidden 'rabbitmq' "$env:WINDIR\System32\cmd.exe" @('/c', "`"$RabbitHome\sbin\rabbitmq-server.bat`"") "$RabbitHome\sbin"
    Wait-Port 5672
}
if (!(Test-Port 8080)) {
    $arguments = @('-jar', 'target\easyjob-0.0.1-SNAPSHOT.jar', '--server.address=127.0.0.1', '--spring.config.additional-location=file:./temp/application-runtime.yml')
    if ($Reindex) { $arguments += '--rag.reindex.enabled=true' }
    Start-Hidden 'java' "$JavaHome\bin\java.exe" $arguments $root
    Wait-Port 8080
}
if (!(Test-Port 8000)) {
    Start-Hidden 'python' $python @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000') (Join-Path $root 'python-agent')
    Wait-Port 8000
}
if (!(Test-Port 3000)) {
    Start-Hidden 'frontend' $Node @('node_modules\vite\bin\vite.js', '--host', '127.0.0.1', '--strictPort') (Join-Path $root 'frontend')
    Wait-Port 3000
}
$health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 10
if ($health.status -ne 'ok') { throw 'Python health check failed.' }
$null = Invoke-RestMethod -Uri 'http://127.0.0.1:3000/api/article/list' -TimeoutSec 10
Write-Host 'Ready: http://127.0.0.1:3000 (frontend), :8080 (Java), :8000 (Agent). Logs: logs/'
if ($KeepAlive) { while ($true) { Start-Sleep -Seconds 30 } }
