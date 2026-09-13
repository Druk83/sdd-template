param(
    [ValidateSet("minimal", "documentation", "repository", "framework")]
    [string]$Profile = "repository",
    [string[]]$Paths,
    [int]$MaxFileSizeKb = 1024,
    [ValidateSet("text","json")]
    [string]$Format = "text",
    [switch]$Strict
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Push-Location $repoRoot
try {
    $tool = ".tools/check-encoding/check_encoding.py"
    $toolArgs = @($tool)
    if ($Paths -and $Paths.Count -gt 0) {
        $toolArgs += @("--paths") + $Paths
    } else {
        $toolArgs += @("--profile", $Profile)
    }
    $toolArgs += @(
        "--max-file-size-kb", "$MaxFileSizeKb",
        "--format", $Format
    )
    if ($Strict) {
        $toolArgs += "--strict"
    }
    & python @toolArgs
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
