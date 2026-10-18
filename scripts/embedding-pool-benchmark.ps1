[CmdletBinding()]
param(
    [string]$JavaHome = 'D:\jdk',
    [string]$Maven = 'D:\IntelliJ IDEA Community Edition 2025.1.3\plugins\maven\lib\maven3\bin\mvn.cmd',
    [string]$MavenRepository = 'D:\IntelliJ IDEA Community Edition 2025.1.3\plugins\maven\lib\maven3\mvn_repo',
    [switch]$Capacity100Only
)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$previousJava = $env:JAVA_HOME
$previousBenchmark = $env:EASYJOB_EMBEDDING_BENCHMARK
Push-Location $taskRoot
try {
    $env:JAVA_HOME = $JavaHome
    $env:EASYJOB_EMBEDDING_BENCHMARK = '1'
    $benchmarkTest = if ($Capacity100Only) { 'EmbeddingPoolBenchmarkTests#compareConsumersAndWorkersAtCapacity100' } else { 'EmbeddingPoolBenchmarkTests' }
    & $Maven "-Dmaven.repo.local=$MavenRepository" '-Deasyjob.build.directory=target/embedding-pool' "-Dtest=$benchmarkTest" test
    if ($LASTEXITCODE -ne 0) { throw "Embedding benchmark failed (exit $LASTEXITCODE)" }
    Write-Output 'Reports: logs/embedding-pool-benchmark.json, logs/embedding-consumer-benchmark.json, logs/embedding-window-benchmark.json, logs/embedding-capacity100-benchmark.json; synthetic loopback API, zero paid model calls.'
} finally {
    $env:JAVA_HOME = $previousJava
    $env:EASYJOB_EMBEDDING_BENCHMARK = $previousBenchmark
    Pop-Location
}
