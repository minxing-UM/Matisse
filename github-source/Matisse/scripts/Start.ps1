# Windows PowerShell 5.1+, intentionally ASCII so double-click works on all locales.
param([switch]$Check, [switch]$PrepareOnly, [switch]$Rebuild, [switch]$SkipEmbeddings)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

function Find-Python {
    $ErrorActionPreference = 'Continue'
    $candidates = @()
    $existingVenv = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $existingVenv) { $candidates += $existingVenv }
    foreach ($name in @('python', 'python3', 'py')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) { $candidates += $command.Source }
    }
    if ($env:LOCALAPPDATA) {
        $candidates += Get-ChildItem -Path "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe" -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName }
    }
    foreach ($candidate in $candidates) {
        try {
            $resolved = & $candidate -c 'import sys; print(sys.executable) if sys.version_info >= (3, 11) else sys.exit(1)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $resolved) { return [string]($resolved | Select-Object -Last 1) }
        } catch { }
    }
    return $null
}

function Install-Package([string]$id) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget is unavailable. Install Python 3.11+ from python.org and Ollama from ollama.com/download/windows, then run Start.cmd again."
    }
    Write-Host "Installing $id using Windows Package Manager..."
    & winget install --id $id --exact --source winget --scope user --accept-source-agreements --accept-package-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) { throw "Installation failed: $id. Install it manually and run Start.cmd again." }
}

try {
    $pythonExecutable = Find-Python
    if (-not $pythonExecutable -and -not $Check) {
        Install-Package 'Python.Python.3.12'
        $pythonExecutable = Find-Python
    }
    if (-not $pythonExecutable) { throw 'Python 3.11+ was not found. Install it, then reopen Start.cmd.' }
    if (-not (Get-Command ollama -ErrorAction SilentlyContinue) -and -not (Test-Path -LiteralPath "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe") -and -not $Check) {
        Install-Package 'Ollama.Ollama'
    }
    if ($Check) {
        & $pythonExecutable (Join-Path $PSScriptRoot 'bootstrap.py') --check
        exit $LASTEXITCODE
    }
    $venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) {
        & $pythonExecutable -m venv (Join-Path $projectRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python virtual environment.' }
    }
    $requirements = Join-Path $projectRoot 'requirements.txt'
    $dependencyMarker = Join-Path $projectRoot '.venv\matisse-requirements.sha256'
    $dependencyHash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash
    $previousHash = if (Test-Path -LiteralPath $dependencyMarker) { (Get-Content -LiteralPath $dependencyMarker -Raw).Trim() } else { '' }
    $ErrorActionPreference = 'Continue'
    & $venvPython -c 'import ollama, pydantic; assert pydantic.VERSION[0] == chr(50)' 2>$null
    $dependenciesPresent = $LASTEXITCODE -eq 0
    $ErrorActionPreference = 'Stop'
    if ($dependencyHash -ne $previousHash -or -not $dependenciesPresent) {
        & $venvPython -m pip install -r $requirements
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check your network and retry.' }
        Set-Content -LiteralPath $dependencyMarker -Value $dependencyHash -Encoding Ascii
    }
    $bootstrapArguments = @((Join-Path $PSScriptRoot 'bootstrap.py'))
    if ($PrepareOnly) { $bootstrapArguments += '--prepare-only' }
    if ($Rebuild) { $bootstrapArguments += '--rebuild' }
    if ($SkipEmbeddings) { $bootstrapArguments += '--skip-embeddings' }
    & $venvPython @bootstrapArguments
    exit $LASTEXITCODE
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
