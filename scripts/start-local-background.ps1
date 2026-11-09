$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$log = Join-Path $root 'logs\local-background-launcher.log'
& (Join-Path $PSScriptRoot 'start-local.ps1') -SkipBuild -KeepAlive *> $log
