param(
    [string]$ComposeFile = 'deploy/observability/compose.yaml',
    [string]$ProjectName = 'easyjob-tracing-lab',
    [string]$CollectorBaseUrl = 'http://127.0.0.1:14318',
    [string]$JaegerBaseUrl = 'http://127.0.0.1:16686'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$traceComposePath = (Resolve-Path -LiteralPath $ComposeFile).Path

function Invoke-TraceCompose {
    param([string[]]$Arguments)
    & docker compose --project-name $ProjectName -f $traceComposePath @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'Tracing Docker Compose command failed.' }
}

function Wait-TraceStored {
    param([string]$TraceId, [string]$OperationName)
    $traceDeadline = [DateTime]::UtcNow.AddSeconds(60)
    while ([DateTime]::UtcNow -lt $traceDeadline) {
        try {
            $traceReply = Invoke-RestMethod -Uri "$JaegerBaseUrl/api/traces/$TraceId" -TimeoutSec 3
            $traceDataProperty = $traceReply.PSObject.Properties['data']
            if ($null -ne $traceDataProperty) {
                foreach ($traceItem in @($traceDataProperty.Value)) {
                    if ($null -eq $traceItem -or $traceItem.traceID -ne $TraceId) { continue }
                    foreach ($traceSpan in @($traceItem.spans)) {
                        if ($traceSpan.operationName -eq $OperationName) { return }
                    }
                }
            }
        } catch {
            # During restart the query endpoint may briefly be unavailable.
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Trace was not queryable within 60 seconds: $TraceId"
}

function Send-TraceProbe {
    param([string]$Phase)
    $probeTraceId = [Guid]::NewGuid().ToString('N')
    $probeSpanId = [Guid]::NewGuid().ToString('N').Substring(0, 16)
    $probeOperation = "persistence.$Phase"
    [long]$probeStart = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() * 1000000
    [long]$probeEnd = $probeStart + 1000000
    $probeBody = @{
        resourceSpans = @(@{
            resource = @{
                attributes = @(@{ key = 'service.name'; value = @{ stringValue = 'easyjob-persistence-check' } })
            }
            scopeSpans = @(@{
                scope = @{ name = 'easyjob.persistence-check'; version = '1.0' }
                spans = @(@{
                    traceId = $probeTraceId
                    spanId = $probeSpanId
                    name = $probeOperation
                    kind = 1
                    startTimeUnixNano = $probeStart.ToString([Globalization.CultureInfo]::InvariantCulture)
                    endTimeUnixNano = $probeEnd.ToString([Globalization.CultureInfo]::InvariantCulture)
                    status = @{ code = 1 }
                })
            })
        })
    } | ConvertTo-Json -Depth 20 -Compress
    $probeReply = Invoke-RestMethod -Method Post -Uri "$CollectorBaseUrl/v1/traces" `
        -ContentType 'application/json' -Body $probeBody -TimeoutSec 10
    if ($null -ne $probeReply) {
        $partialProperty = $probeReply.PSObject.Properties['partialSuccess']
        if ($null -ne $partialProperty -and $null -ne $partialProperty.Value) {
            $rejectedProperty = $partialProperty.Value.PSObject.Properties['rejectedSpans']
            if ($null -ne $rejectedProperty -and [long]$rejectedProperty.Value -gt 0) {
                throw 'Collector rejected the synthetic persistence probe.'
            }
        }
    }
    Wait-TraceStored -TraceId $probeTraceId -OperationName $probeOperation
    return @{ TraceId = $probeTraceId; OperationName = $probeOperation }
}

Invoke-TraceCompose -Arguments @('config', '--quiet')
$firstProbe = Send-TraceProbe -Phase 'before-restart'
Write-Host "PASS stored synthetic trace: $($firstProbe.TraceId)"

Invoke-TraceCompose -Arguments @('restart', 'jaeger')
Wait-TraceStored -TraceId $firstProbe.TraceId -OperationName $firstProbe.OperationName
Write-Host 'PASS original trace survives Jaeger restart'

Invoke-TraceCompose -Arguments @('up', '-d', '--no-deps', '--force-recreate', 'jaeger')
Wait-TraceStored -TraceId $firstProbe.TraceId -OperationName $firstProbe.OperationName
Write-Host 'PASS original trace survives container recreation with the same volume'

$secondProbe = Send-TraceProbe -Phase 'after-recreate'
Write-Host "PASS newly written trace after recreation: $($secondProbe.TraceId)"
Write-Host 'Persistence check finished; only synthetic tracing data was submitted.'
