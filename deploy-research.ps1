[CmdletBinding()]
param(
    [ValidateSet('mock', 'api')][string]$Llm = 'mock',
    [string]$TaskConfig = 'configs/demo.yaml',
    [string]$ModelConfig = 'models.toml',
    [string]$RunDir,
    [string]$Python = 'python',
    [switch]$SkipInstall,
    [switch]$PrepareOnly,
    [switch]$DeployLocalModel,
    [switch]$RunTests
)
$ErrorActionPreference = 'Stop'
function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Executable" }
}
Push-Location -LiteralPath $PSScriptRoot
try {
    $venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) {
        if ($SkipInstall) { throw 'Virtual environment missing; omit -SkipInstall.' }
        Invoke-Checked $Python @('-c', 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"')
        Invoke-Checked $Python @('-m', 'venv', '.venv')
    }
    if (-not $SkipInstall) {
        Invoke-Checked $venvPython @('-m', 'pip', 'install', '-r', 'requirements.txt')
    }
    if (-not (Test-Path -LiteralPath $ModelConfig)) {
        if ($ModelConfig -ne 'models.toml') { throw 'Specified model configuration does not exist.' }
        Copy-Item -LiteralPath 'models.example.toml' -Destination 'models.toml'
    }
    if ($DeployLocalModel) {
        & (Join-Path $PSScriptRoot 'deploy.ps1') -PrepareOnly -DeployLocalModel -ConfigPath $ModelConfig
        if ($LASTEXITCODE -ne 0) { throw 'Local model preparation failed.' }
    }
    if ($TaskConfig -eq 'configs/demo.yaml' -and -not (Test-Path -LiteralPath 'data/synthetic_demo.csv')) {
        Invoke-Checked $venvPython @('-m', 'lazyresearch.science', 'generate-demo', '--output', 'data/synthetic_demo.csv')
    }
    if ($RunTests) { Invoke-Checked $venvPython @('-m', 'pytest', '-q') }
    if (-not $PrepareOnly) {
        if (-not $RunDir) { $RunDir = Join-Path 'runs' ([guid]::NewGuid().ToString('N')) }
        Invoke-Checked $venvPython @('-m', 'lazyresearch.science', 'run', '--config', $TaskConfig,
            '--llm', $Llm, '--model-config', $ModelConfig, '--run-dir', $RunDir)
        Write-Host "Research artifacts: $RunDir"
        Write-Host "Report: $RunDir\report.md"
    }
} finally {
    Pop-Location
}
