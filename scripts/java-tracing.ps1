# Shared JVM arguments for Start-Process / Start-Hidden argument lines.
function Get-JavaTracingArguments {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$ProjectRoot,

        [Parameter(Mandatory = $true)]
        [ValidateSet('easyjob-auth', 'easyjob-blog', 'easyjob-gateway')]
        [string]$ServiceName
    )

    $projectDirectory = [IO.Path]::GetFullPath($ProjectRoot)
    $agentPath = Join-Path $projectDirectory 'tools\observability\opentelemetry-javaagent.jar'
    $configPath = Join-Path $projectDirectory 'tools\observability\otel-java.properties'
    foreach ($requiredFile in @($agentPath, $configPath)) {
        if (!(Test-Path -LiteralPath $requiredFile -PathType Leaf) -or
            (Get-Item -LiteralPath $requiredFile).Length -eq 0) {
            throw "Missing or empty Java tracing file: $requiredFile. Complete tracing tutorial steps 5.1 and 5.3 before starting or restarting services."
        }
    }

    # Start-Process joins ArgumentList with spaces. Keep quotes for paths with spaces.
    return @(
        ('"-javaagent:{0}"' -f $agentPath)
        ('"-Dotel.javaagent.configuration-file={0}"' -f $configPath)
        ('-Dotel.service.name={0}' -f $ServiceName)
    )
}
