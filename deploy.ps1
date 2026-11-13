[CmdletBinding()]
param(
    [string]$Python,
    [string]$ConfigPath,
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,
    [switch]$DeployLocalModel,
    [switch]$SkipBuild,
    [switch]$PrepareOnly
)

$ErrorActionPreference = 'Stop'

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Executable $($Arguments -join ' ')"
    }
}

function Find-Python {
    if ($Python) {
        return (Get-Command $Python -CommandType Application).Source
    }
    foreach ($candidate in (Get-Command python.exe -CommandType Application -All -ErrorAction SilentlyContinue)) {
        if ($candidate.Source -like '*\Microsoft\WindowsApps\*') {
            continue
        }
        & $candidate.Source -c "import importlib.util, sys; sys.exit(sys.version_info < (3, 11) or importlib.util.find_spec('ensurepip') is None)"
        if ($LASTEXITCODE -eq 0) {
            return $candidate.Source
        }
    }
    throw 'Install Python 3.11+ with pip or pass -Python with the full path to python.exe.'
}

function Get-ModelConfig {
    $code = @'
import json
from lazyresearch.configuration import load_model_config

config = load_model_config()
print(json.dumps({
    'enabled': config.local.enabled,
    'base_url': config.local.base_url,
    'model': config.local.model,
    'prompt_ready': bool(config.prompts.local),
    'cloud_enabled': config.cloud.enabled,
    'cloud_model_ready': bool(config.cloud.base_url and config.cloud.model),
    'cloud_key_in_file': bool(config.cloud.api_key.get_secret_value().strip()),
    'cloud_key_env': config.cloud.api_key_env if config.cloud.api_key_env.isidentifier() else '',
    'cloud_prompt_ready': bool(config.prompts.planning or config.prompts.diagnosis),
}))
'@
    $json = & $venvPython -c $code
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not load the model configuration.'
    }
    return $json | ConvertFrom-Json
}

function Find-Ollama {
    $command = Get-Command ollama.exe -CommandType Application -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $installed = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (Test-Path -LiteralPath $installed -PathType Leaf) {
        return $installed
    }
    throw 'Ollama was not found. Install it from https://ollama.com/download/windows and rerun this command.'
}

function Deploy-Ollama {
    param($Local, [string]$OllamaPath)
    if (-not $Local.enabled -or -not $Local.model -or -not $Local.prompt_ready) {
        throw 'Set local.enabled, local.model and prompts.local before using -DeployLocalModel.'
    }
    if ($Local.base_url -notmatch '^http://(127\.0\.0\.1|localhost)(:\d+)?/v1$') {
        throw '-DeployLocalModel requires a loopback Ollama base_url ending in /v1. Start custom endpoints separately.'
    }
    $endpoint = ([uri]$Local.base_url).GetLeftPart([System.UriPartial]::Authority)
    $tagsUrl = "$endpoint/api/tags"
    $previousHost = $env:OLLAMA_HOST
    $env:OLLAMA_HOST = $endpoint
    try {
        try {
            $tags = Invoke-RestMethod -Uri $tagsUrl -TimeoutSec 3
        } catch {
            Write-Host "Starting Ollama at $endpoint..."
            Start-Process -FilePath $OllamaPath -ArgumentList 'serve' -WindowStyle Hidden
            $tags = $null
            for ($attempt = 0; $attempt -lt 20; $attempt++) {
                Start-Sleep -Milliseconds 500
                try {
                    $tags = Invoke-RestMethod -Uri $tagsUrl -TimeoutSec 2
                    break
                } catch {
                    continue
                }
            }
        }
        if (-not $tags) {
            throw "Ollama did not respond at $tagsUrl."
        }
        $model = $Local.model
        if (($model -split '/')[-1] -notmatch ':') {
            $model += ':latest'
        }
        if ($tags.models.name -notcontains $model) {
            if ($model -eq 'qwen2.5:1.5b') {
                $weights = Join-Path $PSScriptRoot 'models\qwen2.5-1.5b-instruct-q4_k_m.gguf'
                if (-not (Test-Path -LiteralPath $weights -PathType Leaf) -or
                    (Get-Item -LiteralPath $weights).Length -lt 100MB) {
                    throw 'Bundled Qwen weights are missing or still an LFS pointer. Run git lfs pull or extract the complete project bundle.'
                }
                Write-Host "Verifying and importing bundled Qwen weights (1.12 GB)..."
                $expected = '6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e'
                if ((Get-FileHash -LiteralPath $weights -Algorithm SHA256).Hash -ne $expected) {
                    throw 'Bundled Qwen weights failed SHA-256 verification.'
                }
                $modelfile = Join-Path $PSScriptRoot 'models\Modelfile'
                Invoke-Checked $OllamaPath @('create', $model, '-f', $modelfile)
            } else {
                Invoke-Checked $OllamaPath @('pull', $Local.model)
            }
        }
        Write-Host "Ollama model available: $model"
    } finally {
        $env:OLLAMA_HOST = $previousHost
    }
}

$previousConfig = $env:LAZYRESEARCH_MODEL_CONFIG
if ($ConfigPath) {
    $env:LAZYRESEARCH_MODEL_CONFIG = (Resolve-Path -LiteralPath $ConfigPath).Path
} elseif ($previousConfig) {
    $env:LAZYRESEARCH_MODEL_CONFIG = (Resolve-Path -LiteralPath $previousConfig).Path
}

Push-Location -LiteralPath $PSScriptRoot
try {
    if ($DeployLocalModel) {
        $ollamaPath = Find-Ollama
    }
    if (-not $PrepareOnly) {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
        try {
            $listener.Start()
        } catch [System.Net.Sockets.SocketException] {
            if ($_.Exception.SocketErrorCode -ne [System.Net.Sockets.SocketError]::AddressAlreadyInUse) {
                throw
            }
            throw "Port $Port is already in use. Stop the existing server or pass -Port with a free port."
        } finally {
            $listener.Stop()
        }
    }
    if (-not $env:LAZYRESEARCH_MODEL_CONFIG -and -not (Test-Path -LiteralPath 'models.toml')) {
        Copy-Item -LiteralPath 'models.example.toml' -Destination 'models.toml'
    }
    $venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if ($SkipBuild -and (-not (Test-Path -LiteralPath $venvPython) -or
                         -not (Test-Path -LiteralPath 'web\dist\index.html'))) {
        throw 'Run deploy.ps1 without -SkipBuild once to prepare the environment and frontend.'
    }
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Invoke-Checked (Find-Python) @('-m', 'venv', '.venv')
    }
    & $venvPython -c "import importlib.util, sys; sys.exit(importlib.util.find_spec('pip') is None)"
    if ($LASTEXITCODE -ne 0) {
        Invoke-Checked $venvPython @('-m', 'ensurepip', '--upgrade')
    }
    if (-not $SkipBuild) {
        Write-Host 'Installing Python dependencies...'
        Invoke-Checked $venvPython @('-m', 'pip', 'install', '--disable-pip-version-check', '-r', 'requirements.txt')
    }
    $local = Get-ModelConfig
    if ($local.cloud_enabled) {
        if (-not $local.cloud_model_ready -or -not $local.cloud_prompt_ready) {
            throw 'Cloud is enabled. Configure its API URL, model and prompt.'
        }
    }
    if ($local.cloud_enabled -and -not $local.cloud_key_in_file) {
        $cloudKeyName = $local.cloud_key_env
        if (-not $cloudKeyName) {
            throw 'Set cloud.api_key or specify a cloud.api_key_env variable name.'
        }
        $previousCloudKey = [Environment]::GetEnvironmentVariable($cloudKeyName, 'Process')
        if (-not $previousCloudKey) {
            $userCloudKey = [Environment]::GetEnvironmentVariable($cloudKeyName, 'User')
            if (-not $userCloudKey) {
                throw "Set the cloud API key in the $cloudKeyName environment variable."
            }
            [Environment]::SetEnvironmentVariable($cloudKeyName, $userCloudKey, 'Process')
        }
    }
    if (-not $SkipBuild) {
        $npm = (Get-Command npm.cmd -CommandType Application).Source
        Write-Host 'Installing and building the web frontend...'
        Invoke-Checked $npm @('--prefix', 'web', 'ci')
        Invoke-Checked $npm @('--prefix', 'web', 'run', 'build')
    }
    if ($DeployLocalModel) {
        Deploy-Ollama $local $ollamaPath
    }
    if (-not $PrepareOnly) {
        Write-Host "LazyResearch: http://127.0.0.1:$Port"
        Invoke-Checked $venvPython @('-m', 'uvicorn', 'lazyresearch.api:create_app', '--factory',
                                    '--host', '127.0.0.1', '--port', $Port)
    }
} finally {
    if ($cloudKeyName) {
        [Environment]::SetEnvironmentVariable($cloudKeyName, $previousCloudKey, 'Process')
    }
    Pop-Location
    $env:LAZYRESEARCH_MODEL_CONFIG = $previousConfig
}
