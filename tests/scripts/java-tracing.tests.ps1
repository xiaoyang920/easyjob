$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$fixtureRoot = Join-Path $repositoryRoot ('temp\java tracing tests ' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $fixtureRoot -Force | Out-Null
$passedChecks = 0

function Assert-TraceCondition([bool]$Condition, [string]$Message) {
    if (!$Condition) { throw $Message }
}

function Complete-TraceCheck([string]$Name) {
    $script:passedChecks += 1
    Write-Host "PASS $Name"
}

function New-TraceFixture([string]$Name, [switch]$MissingAgent, [switch]$MissingConfig) {
    $directory = Join-Path $fixtureRoot $Name
    $scripts = Join-Path $directory 'scripts'
    $assets = Join-Path $directory 'tools\observability'
    New-Item -ItemType Directory -Path $scripts, $assets -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $repositoryRoot 'scripts\java-tracing.ps1') -Destination $scripts
    if (!$MissingAgent) {
        [IO.File]::WriteAllText((Join-Path $assets 'opentelemetry-javaagent.jar'), 'fixture-only')
    }
    if (!$MissingConfig) {
        [IO.File]::WriteAllText((Join-Path $assets 'otel-java.properties'), 'fixture-only')
    }
    $authJar = Join-Path $directory 'auth-service\target\easyjob-auth-0.0.1-SNAPSHOT.jar'
    New-Item -ItemType Directory -Path (Split-Path -Parent $authJar) -Force | Out-Null
    [IO.File]::WriteAllText($authJar, 'fixture-only')
    foreach ($name in @('restart-java.ps1', 'restart-gateway.ps1', 'restart-auth.ps1')) {
        $tokens = $null
        $errors = $null
        $sourcePath = Join-Path $repositoryRoot ('scripts\' + $name)
        $ast = [Management.Automation.Language.Parser]::ParseFile($sourcePath, [ref]$tokens, [ref]$errors)
        Assert-TraceCondition ($errors.Count -eq 0) "Cannot parse $name"
        $healthLoop = $ast.EndBlock.Statements | Where-Object {
            $_ -is [Management.Automation.Language.ForStatementAst]
        } | Select-Object -First 1
        Assert-TraceCondition ($null -ne $healthLoop) "Cannot locate readiness loop in $name"
        # Execute only preparation and launch; all process commands are mocked below.
        $prefix = [IO.File]::ReadAllText($sourcePath).Substring(0, $healthLoop.Extent.StartOffset)
        [IO.File]::WriteAllText((Join-Path $scripts $name), $prefix)
    }
    return $directory
}

$validRoot = New-TraceFixture -Name 'valid root with spaces'
$missingAgentRoot = New-TraceFixture -Name 'missing agent' -MissingAgent
$missingConfigRoot = New-TraceFixture -Name 'missing config' -MissingConfig

$cases = @(
    @{ Script = 'restart-java.ps1'; Service = 'easyjob-blog'; Port = 8080; Jar = 'target\easyjob-0.0.1-SNAPSHOT.jar'; Runtime = 'application-runtime.yml' }
    @{ Script = 'restart-gateway.ps1'; Service = 'easyjob-gateway'; Port = 8090; Jar = 'gateway\target\easyjob-gateway-0.0.1-SNAPSHOT.jar'; Runtime = 'gateway-runtime.yml' }
    @{ Script = 'restart-auth.ps1'; Service = 'easyjob-auth'; Port = 8081; Jar = 'auth-service\target\easyjob-auth-0.0.1-SNAPSHOT.jar'; Runtime = 'auth-runtime.yml' }
)

function Invoke-TraceRestartCheck($Case, [string]$Directory, [switch]$ExpectFailure) {
    $capture = @{ Stops = @(); Starts = @(); Inspections = 0 }
    $scenario = $Case
    function Get-CimInstance {
        param([string]$ClassName, [string]$Filter)
        $capture.Inspections += 1
        return [pscustomobject]@{
            ExecutablePath = 'D:\jdk\bin\java.exe'
            CommandLine = '-jar ' + $scenario.Jar + ' --spring.config.additional-location=file:./temp/' + $scenario.Runtime
            ProcessId = 777777
        }
    }
    function Get-NetTCPConnection {
        [CmdletBinding()]
        param([int]$LocalPort, [string]$State)
        return [pscustomobject]@{ LocalAddress = '127.0.0.1'; OwningProcess = 777777 }
    }
    function Stop-Process {
        [CmdletBinding()]
        param([int]$Id, [switch]$Force)
        Assert-TraceCondition ($Id -eq 777777) 'Unexpected process target in restart test'
        $capture.Stops += $Id
    }
    function Start-Process {
        [CmdletBinding()]
        param([string]$FilePath, [string[]]$ArgumentList, [string]$WorkingDirectory,
              [string]$WindowStyle, [string]$RedirectStandardOutput,
              [string]$RedirectStandardError, [switch]$PassThru)
        $capture.Starts += ,$ArgumentList
        Assert-TraceCondition ($WindowStyle -eq 'Hidden') 'Restart must remain hidden'
        return [pscustomobject]@{ Id = 888888 }
    }
    $caught = $null
    try { & (Join-Path $Directory ('scripts\' + $Case.Script)) } catch { $caught = $_ }
    if ($ExpectFailure) {
        Assert-TraceCondition ($null -ne $caught) 'Missing tracing assets must fail'
        Assert-TraceCondition ($caught.Exception.Message -like 'Missing or empty Java tracing file:*') 'Unexpected preflight error'
        Assert-TraceCondition ($capture.Inspections -eq 0 -and $capture.Stops.Count -eq 0 -and $capture.Starts.Count -eq 0) 'Preflight failure must preserve the running service'
        return
    }
    if ($null -ne $caught) { throw $caught }
    Assert-TraceCondition ($capture.Stops.Count -eq 1 -and $capture.Starts.Count -eq 1) 'Expected one verified stop and one launch'
    $arguments = $capture.Starts[0]
    Assert-TraceCondition ($arguments[0] -eq ('"-javaagent:{0}"' -f (Join-Path $Directory 'tools\observability\opentelemetry-javaagent.jar'))) 'Agent path with spaces must be quoted'
    Assert-TraceCondition ($arguments[1] -eq ('"-Dotel.javaagent.configuration-file={0}"' -f (Join-Path $Directory 'tools\observability\otel-java.properties'))) 'Config path with spaces must be quoted'
    Assert-TraceCondition ($arguments[2] -eq ('-Dotel.service.name=' + $Case.Service)) 'Wrong service identity'
    Assert-TraceCondition ($arguments[3] -eq '-jar' -and $arguments[4] -eq $Case.Jar) 'JVM flags must precede the application JAR'
    Assert-TraceCondition ($arguments -contains '--spring.profiles.include=tracing') 'Tracing profile missing'
    Assert-TraceCondition ($arguments -contains ('--spring.config.additional-location=file:./temp/' + $Case.Runtime)) 'Original runtime configuration missing'
}

foreach ($case in $cases) {
    Invoke-TraceRestartCheck -Case $case -Directory $validRoot
    Complete-TraceCheck ($case.Script + ' launch arguments and existing process verification')
    Invoke-TraceRestartCheck -Case $case -Directory $missingAgentRoot -ExpectFailure
    Complete-TraceCheck ($case.Script + ' preserves service when agent is missing')
    Invoke-TraceRestartCheck -Case $case -Directory $missingConfigRoot -ExpectFailure
    Complete-TraceCheck ($case.Script + ' preserves service when config is missing')
}

function Test-TraceMainLauncher {
    $tokens = $null
    $errors = $null
    $ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $repositoryRoot 'scripts\start-local.ps1'), [ref]$tokens, [ref]$errors)
    Assert-TraceCondition ($errors.Count -eq 0) 'Cannot parse main launcher'
    $root = $validRoot
    $JavaHome = 'D:\jdk'
    . (Join-Path $validRoot 'scripts\java-tracing.ps1')
    $capture = @{ Calls = @() }
    function Start-Hidden {
        param([string]$Name, [string]$File, [string]$ArgumentLine, [string]$Directory)
        $capture.Calls += [pscustomobject]@{ Name = $Name; Arguments = $ArgumentLine }
    }
    $assignments = $ast.FindAll({ param($node) $node -is [Management.Automation.Language.AssignmentStatementAst] }, $true)
    foreach ($prefix in @('auth', 'blog', 'gateway')) {
        $name = $prefix + 'TracingArguments'
        $assignment = $assignments | Where-Object { $_.Left.Extent.Text -match ('\$' + $name + '$') } | Select-Object -First 1
        Assert-TraceCondition ($null -ne $assignment) "Tracing arguments missing for $prefix"
        Invoke-Expression $assignment.Extent.Text
        $launchLine = $assignments | Where-Object {
            $_.Right.Extent.Text -match ('\$' + $name + '\b') -and $_.Right.Extent.Text -match '\-jar '
        } | Select-Object -First 1
        Assert-TraceCondition ($null -ne $launchLine) "Launch line missing for $prefix"
        Invoke-Expression $launchLine.Extent.Text
    }
    $commands = $ast.FindAll({ param($node) $node -is [Management.Automation.Language.CommandAst] -and $node.GetCommandName() -eq 'Start-Hidden' }, $true)
    foreach ($name in @('auth', 'java', 'gateway')) {
        $command = $commands | Where-Object { $_.CommandElements[1].Extent.Text.Trim("'") -eq $name } | Select-Object -First 1
        Assert-TraceCondition ($null -ne $command) "Launch command missing for $name"
        Invoke-Expression $command.Extent.Text
    }
    foreach ($call in $capture.Calls) {
        $service = if ($call.Name -eq 'java') { 'easyjob-blog' } else { 'easyjob-' + $call.Name }
        Assert-TraceCondition ($call.Arguments.Contains('-Dotel.service.name=' + $service)) 'Main launcher service identity mismatch'
        Assert-TraceCondition ($call.Arguments.IndexOf('-javaagent:') -lt $call.Arguments.IndexOf(' -jar ')) 'Main launcher JVM argument order'
        Assert-TraceCondition ($call.Arguments.Contains('--spring.profiles.include=tracing')) 'Main launcher tracing profile missing'
        Assert-TraceCondition ($call.Arguments.Contains('"-javaagent:' + (Join-Path $validRoot 'tools\observability\opentelemetry-javaagent.jar') + '"')) 'Main launcher must preserve quoted paths'
    }
    Assert-TraceCondition ($capture.Calls.Count -eq 3) 'Expected all three Java service launch lines'
}

Test-TraceMainLauncher
Complete-TraceCheck 'main launcher argument construction for auth, blog and gateway'
Write-Host "$passedChecks checks passed; no real service was started or stopped."
