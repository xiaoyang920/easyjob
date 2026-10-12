param(
    [switch]$OpenBrowser,
    [switch]$Check,
    [switch]$KeepAlive,
    [switch]$Build,
    [switch]$SkipBuild,
    [switch]$Migrate,
    [switch]$Reindex,
    [ValidateRange(30,900)][int]$TimeoutSeconds = 180,
    [string]$MySqlService = 'MySQL',
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
$desktop = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
$image = 'redis/redis-stack@sha256:5d5154123426693540ea6c1d9e638eae2bf2024879c839db6fcfdd7717e817c7'
$jar = Join-Path $root 'target\easyjob-0.0.1-SNAPSHOT.jar'
$runtime = Join-Path $root 'temp\application-runtime.yml'

function Write-Step([string]$Message) { Write-Host ('[{0:HH:mm:ss}] {1}' -f (Get-Date), $Message) }

function Test-Port([int]$Port) {
    $client = [Net.Sockets.TcpClient]::new()
    try { return $client.ConnectAsync('127.0.0.1', $Port).Wait(300) -and $client.Connected }
    catch { return $false } finally { $client.Dispose() }
}

function Wait-Ready([string]$Name, [scriptblock]$Probe, $Process = $null) {
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        if (& $Probe) { Write-Step "$Name ready."; return }
        if ($null -ne $Process) {
            $Process.Refresh()
            if ($Process.HasExited) { throw "$Name exited (code $($Process.ExitCode)). Check $logs\$Name.err.log and $Name.out.log." }
        }
        Start-Sleep -Seconds 1
    }
    throw "$Name not ready after $TimeoutSeconds seconds. Check logs/; resolve the failure and run again."
}

function Start-Hidden([string]$Name, [string]$File, [string]$ArgumentLine, [string]$Directory) {
    $process = Start-Process -FilePath $File -ArgumentList $ArgumentLine -WorkingDirectory $Directory `
        -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs "$Name.out.log") `
        -RedirectStandardError (Join-Path $logs "$Name.err.log") -PassThru
    Write-Step "$Name started (PID $($process.Id))."
    return $process
}

function Invoke-Logged([string]$Name, [string]$File, [string[]]$Arguments, [string]$Directory) {
    # Native stderr is logged; its exit code decides success, including on Windows PowerShell 5.
    $ErrorActionPreference = 'Continue'
    Push-Location -LiteralPath $Directory
    try {
        & $File @Arguments *> (Join-Path $logs "$Name.log")
        $code = $LASTEXITCODE
    } finally { Pop-Location }
    if ($code -ne 0) { throw "$Name failed (exit $code). Check $logs\$Name.log." }
}

function Test-Docker {
    $ErrorActionPreference = 'Continue'
    & $docker info --format '{{.ServerVersion}}' *> $null
    return $LASTEXITCODE -eq 0
}

function Test-Java {
    try {
        $result = Invoke-RestMethod 'http://127.0.0.1:8080/api/article/list?page=1&size=1' -TimeoutSec 3
        return $result.code -eq 200 -and $null -ne $result.data
    } catch { return $false }
}

function Test-Agent {
    try { return (Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 3).status -eq 'ok' }
    catch { return $false }
}

function Test-Es {
    try {
        $info = Invoke-RestMethod 'http://127.0.0.1:9200/' -TimeoutSec 3
        $health = Invoke-RestMethod 'http://127.0.0.1:9200/_cluster/health?wait_for_status=yellow&timeout=1s' -TimeoutSec 3
        return $null -ne $info.version.number -and $health.status -in @('yellow','green') -and !$health.timed_out
    } catch { return $false }
}

function Test-Frontend {
    try {
        $result = Invoke-RestMethod 'http://127.0.0.1:3000/api/article/list?page=1&size=1' -TimeoutSec 3
        $page = Invoke-WebRequest 'http://127.0.0.1:3000/' -UseBasicParsing -TimeoutSec 3
        return $result.code -eq 200 -and $page.Content -match 'id="app"'
    } catch { return $false }
}

function Start-RedisContainer([string]$Name, [int]$Port, [string]$Volume, [switch]$Checkpoint) {
    if (Test-Port $Port) { Write-Step "Redis :$Port already listening; verifying protocol below."; return }
    $existing = @(& $docker ps -a --format '{{.Names}}')
    if ($LASTEXITCODE -ne 0) { throw 'Cannot list Docker containers.' }
    $container = $Name
    if ($Port -eq 6379 -and $existing -contains 'redis-stack') { $container = 'redis-stack' }
    if ($existing -contains $container) {
        & $docker start $container | Out-Null
    } else {
        $arguments = @('run','-d','--name',$container,'--restart','unless-stopped',
            '-p',"127.0.0.1:${Port}:6379",'-v',"${Volume}:/data")
        if ($Checkpoint) {
            $arguments += @('--entrypoint','redis-server',$image,'--dir','/data','--appendonly','yes',
                '--protected-mode','no','--loadmodule','/opt/redis-stack/lib/redisearch.so',
                '--loadmodule','/opt/redis-stack/lib/rejson.so')
        } else { $arguments += $image }
        & $docker @arguments | Out-Null
    }
    if ($LASTEXITCODE -ne 0) { throw "Redis container $container failed to start." }
    Wait-Ready "Redis-$Port" { Test-Port $Port }
}

function Test-JarFresh {
    if (!(Test-Path -LiteralPath $jar -PathType Leaf)) { return $false }
    $modified = (Get-Item -LiteralPath $jar).LastWriteTimeUtc
    $sources = @(Get-ChildItem -LiteralPath (Join-Path $root 'src\main') -Recurse -File)
    $sources += Get-Item -LiteralPath (Join-Path $root 'pom.xml')
    return @($sources | Where-Object { $_.LastWriteTimeUtc -gt $modified }).Count -eq 0
}

function Check-Prerequisites {
    $required = @($python, "$JavaHome\bin\java.exe", $Node,
        "$ElasticsearchHome\bin\elasticsearch.bat", "$RabbitHome\sbin\rabbitmq-server.bat",
        (Join-Path $root 'src\main\resources\application.yml'), (Join-Path $root 'python-agent\.env'),
        (Join-Path $root 'frontend\node_modules\vite\bin\vite.js'))
    if (!$SkipBuild) { $required += $Maven }
    if (!(Test-Port 6379) -or !(Test-Port 6380)) { $required += @($docker,$desktop) }
    foreach ($path in $required) {
        if (!(Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing prerequisite: $path. See README.md (Windows launcher)." }
    }
    if ($Build -and $SkipBuild) { throw 'Use -Build or -SkipBuild, not both.' }
    if ($SkipBuild -and !(Test-Path -LiteralPath $jar)) { throw 'No existing Java JAR. Run without -SkipBuild first.' }
    if (($Build -or $Reindex) -and (Test-Port 8080)) { throw 'Java is already running. Stop the verified project Java process before -Build/-Reindex.' }
    if ($Migrate -and ((Test-Port 8080) -or (Test-Port 8000))) { throw 'Stop Java and Agent before requesting -Migrate.' }
}

# Serialize launchers for this checkout; repeated double-clicks never launch competing stacks.
$hash = [Security.Cryptography.SHA256]::Create()
try { $identity = ([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($root.ToLowerInvariant())))).Replace('-','') }
finally { $hash.Dispose() }
$mutex = [Threading.Mutex]::new($false, "Local\EasyJobStart_$identity")
$ownsMutex = $false
try {
    try { $ownsMutex = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $ownsMutex = $true }
    if (!$ownsMutex) { Write-Host 'Another launcher is already starting this checkout. Check its window.'; return }
    Check-Prerequisites
    if ($Check) {
        Write-Host 'Prerequisites found. Check mode does not start services, build, or change database/configuration.'
        foreach ($port in @(3306,6379,6380,5672,9200,8080,8000,3000)) { Write-Host (':{0} listening={1}' -f $port,(Test-Port $port)) }
        Write-Host ('Java build needed when stopped: ' + !(Test-JarFresh))
        return
    }
    New-Item -ItemType Directory -Path $logs -Force | Out-Null
    $env:JAVA_HOME = $JavaHome
    $env:Path = "$JavaHome\bin;$(Split-Path -Parent $Node);$env:Path"
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    Invoke-Logged 'python-dependencies' $python @('-c','import uvicorn, yaml, redis, httpx, databases, langgraph.checkpoint.redis') $root

    Write-Step '1/7 Checking MySQL.'
    if (!(Test-Port 3306)) {
        $service = Get-Service -Name $MySqlService -ErrorAction SilentlyContinue
        if ($null -eq $service) { throw "MySQL :3306 is stopped and service '$MySqlService' was not found. Set -MySqlService to your installed service." }
        try { Start-Service -Name $MySqlService }
        catch { throw "Cannot start service $MySqlService. Start MySQL once as administrator, then run this launcher again." }
        Wait-Ready 'mysql' { Test-Port 3306 }
    }
    if (!(Test-Path -LiteralPath $runtime)) {
        Write-Step 'Preparing missing local runtime configuration (secrets are not printed).'
        Invoke-Logged 'prepare-local' $python @('scripts\prepare-local.py') $root
    }

    Write-Step '2/7 Starting cache Redis and Checkpoint Redis.'
    if (!(Test-Port 6379) -or !(Test-Port 6380)) {
        if (!(Test-Docker)) {
            Write-Step 'Starting Docker Desktop; first startup may take a few minutes.'
            Start-Process -FilePath $desktop -WindowStyle Hidden | Out-Null
            Wait-Ready 'Docker' { Test-Docker }
        }
        Start-RedisContainer 'easyjob-cache-redis' 6379 'easyjob-cache-data'
        Start-RedisContainer 'easyjob-checkpoint-redis' 6380 'easyjob-checkpoint-data' -Checkpoint
    }
    Invoke-Logged 'dependency-health' $python @('scripts\local-dependency-health.py') $root
    if ($Migrate) {
        Write-Step 'Applying explicitly requested database migrations.'
        Invoke-Logged 'database-migration' $python @('-m','app.migrate') (Join-Path $root 'python-agent')
    }

    Write-Step '3/7 Starting Elasticsearch.'
    $esProcess = $null
    if (!(Test-Port 9200)) {
        $env:ES_JAVA_HOME = $JavaHome
        $env:ES_JAVA_OPTS = '-Xms1g -Xmx1g'
        $esProcess = Start-Hidden 'elasticsearch' "$env:WINDIR\System32\cmd.exe" `
            ('/d /s /c ""' + "$ElasticsearchHome\bin\elasticsearch.bat" + '""') $ElasticsearchHome
    }
    Wait-Ready 'elasticsearch' { Test-Es } $esProcess

    Write-Step '4/7 Starting RabbitMQ.'
    $rabbitProcess = $null
    if (!(Test-Port 5672)) {
        $rabbitProcess = Start-Hidden 'rabbitmq' "$env:WINDIR\System32\cmd.exe" `
            ('/d /s /c ""' + "$RabbitHome\sbin\rabbitmq-server.bat" + '""') "$RabbitHome\sbin"
    }
    Wait-Ready 'rabbitmq' { Test-Port 5672 } $rabbitProcess

    Write-Step '5/7 Starting Java backend.'
    $javaProcess = $null
    if (Test-Port 8080) {
        if (!(Test-Java)) { throw 'Port 8080 is occupied but the EasyJob article API is unhealthy. Check logs/java.*.log; no process was stopped.' }
        Write-Step 'Java already running; keeping it. Source changes require a separate restart.'
    } else {
        if ($Build -or (!$SkipBuild -and !(Test-JarFresh))) {
            Write-Step 'Building updated Java sources. Progress: logs/maven-package.log.'
            Invoke-Logged 'maven-package' $Maven @('-q','-DskipTests','-Deasyjob.build.directory=target/local-launcher','package') $root
            Copy-Item -LiteralPath (Join-Path $root 'target\local-launcher\easyjob-0.0.1-SNAPSHOT.jar') -Destination $jar -Force
        }
        $arguments = '-jar target\easyjob-0.0.1-SNAPSHOT.jar --server.address=127.0.0.1 --spring.config.additional-location=file:./temp/application-runtime.yml'
        if ($Reindex) { $arguments += ' --rag.reindex.enabled=true' }
        $javaProcess = Start-Hidden 'java' "$JavaHome\bin\java.exe" $arguments $root
        Wait-Ready 'java' { Test-Java } $javaProcess
    }

    Write-Step '6/7 Starting Python Agent.'
    $agentProcess = $null
    if (!(Test-Port 8000)) {
        $agentProcess = Start-Hidden 'python' $python '-m uvicorn app.main:app --host 127.0.0.1 --port 8000' (Join-Path $root 'python-agent')
    }
    Wait-Ready 'python' { Test-Agent } $agentProcess

    Write-Step '7/7 Starting frontend.'
    $frontendProcess = $null
    if (!(Test-Port 3000)) {
        $frontendProcess = Start-Hidden 'frontend' $Node 'node_modules\vite\bin\vite.js --host 127.0.0.1 --port 3000 --strictPort' (Join-Path $root 'frontend')
    }
    Wait-Ready 'frontend' { Test-Frontend } $frontendProcess
    Write-Host ''
    Write-Host 'READY: http://127.0.0.1:3000' -ForegroundColor Green
    Write-Host 'Java: :8080   Agent: :8000   Logs: logs/'
    Write-Host 'Services run in the background. Closing this launcher does not stop them.'
    if ($OpenBrowser) { Start-Process 'http://127.0.0.1:3000' | Out-Null }
} finally {
    if ($ownsMutex) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
if ($KeepAlive) { while ($true) { Start-Sleep -Seconds 30 } }
