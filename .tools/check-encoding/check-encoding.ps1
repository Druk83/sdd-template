param(
    [string[]]$Paths = @("docs", "README.md", "apps", "services", "scripts", ".manifest", ".requirements", ".tasks", ".issues"),
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
    $toolArgs = @(
        $tool,
        "--paths"
    ) + $Paths + @(
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
