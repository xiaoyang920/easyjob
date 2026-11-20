param(
    [string]$GatewayUrl = 'http://127.0.0.1:8090',
    [string]$JaegerUrl = 'http://127.0.0.1:16686'
)

$ErrorActionPreference = 'Stop'
$response = Invoke-WebRequest -UseBasicParsing -Uri "$GatewayUrl/api/article/list" -TimeoutSec 10
$traceId = [string](@($response.Headers['X-Trace-Id'])[0])
if ($traceId -notmatch '^[0-9a-f]{32}$' -or $traceId -match '^0+$') {
    throw 'Gateway did not return a valid X-Trace-Id.'
}

$deadline = [DateTime]::UtcNow.AddSeconds(30)
do {
    $result = $null
    try { $result = Invoke-RestMethod -Uri "$JaegerUrl/api/traces/$traceId" -TimeoutSec 3 }
    catch { Write-Verbose $_.Exception.Message }
    if ($result) {
        foreach ($trace in @($result.data)) {
            if ($trace.traceID -ne $traceId) { continue }
            $services = @($trace.processes.PSObject.Properties | ForEach-Object { $_.Value.serviceName })
            if ($services -contains 'easyjob-gateway' -and $services -contains 'easyjob-blog') {
                Write-Host "PASS Gateway and Blog share trace $traceId"
                Write-Host "$JaegerUrl/trace/$traceId"
                return
            }
        }
    }
    Start-Sleep -Milliseconds 500
} while ([DateTime]::UtcNow -lt $deadline)

throw "Jaeger did not return both Gateway and Blog for trace $traceId."
