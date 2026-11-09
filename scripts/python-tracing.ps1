function Set-PythonTracingEnvironment {
    # Process-local defaults for the learning launcher; preserve explicit overrides.
    $defaults = @{
        EASYJOB_TRACING_ENABLED = 'true'
        EASYJOB_TRACING_LAB_ONLY = 'true'
        OTEL_SERVICE_NAME = 'easyjob-agent'
        OTEL_EXPORTER_OTLP_ENDPOINT = 'http://127.0.0.1:14318'
        OTEL_TRACES_SAMPLER_ARG = '1.0'
    }
    foreach ($entry in $defaults.GetEnumerator()) {
        if ([string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($entry.Key, 'Process'))) {
            [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process')
        }
    }
}
