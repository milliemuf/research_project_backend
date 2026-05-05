# BugsInPy setup script for Windows / PowerShell.
#
# BugsInPy is a Python-bug benchmark with one folder per project. Unlike
# Defects4J it does NOT come with a global runner: each bug expects a
# project-specific virtualenv with that project's pinned dependencies.
#
# This script creates per-project venvs lazily, so you can start small
# (one or two projects) and grow the set as you go.

param(
    [string]$BugsInPyRoot = "$PSScriptRoot\..\data\bug_datasets\bugsinpy",
    [string[]]$Projects = @("PySnooper", "thefuck"),  # small projects, fast to set up
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) {
    Write-Error "Python not found. Set -Python explicitly or add python to PATH."
}

$root = Resolve-Path -LiteralPath $BugsInPyRoot -ErrorAction SilentlyContinue
if (-not $root) {
    Write-Host "==> $BugsInPyRoot not found; cloning BugsInPy..." -ForegroundColor Cyan
    $parent = Split-Path -Parent $BugsInPyRoot
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    git clone https://github.com/soarsmu/BugsInPy $BugsInPyRoot
    $root = Resolve-Path -LiteralPath $BugsInPyRoot
}

$projectsDir = Join-Path $root.Path "projects"
if (-not (Test-Path $projectsDir)) {
    Write-Error "projects/ directory not found under $($root.Path)"
}

foreach ($name in $Projects) {
    $projDir = Join-Path $projectsDir $name
    if (-not (Test-Path $projDir)) {
        Write-Warning "Project $name not present in BugsInPy checkout; skipping"
        continue
    }
    Write-Host "==> Preparing project: $name" -ForegroundColor Cyan
    $venvDir = Join-Path $projDir ".venv"
    if (-not (Test-Path $venvDir)) {
        & $Python -m venv $venvDir
    }
    $pip = Join-Path $venvDir "Scripts\pip.exe"
    if (-not (Test-Path $pip)) {
        Write-Warning "Could not find pip at $pip; skipping deps for $name"
        continue
    }
    & $pip install --upgrade pip --quiet

    # Install project-specific deps if a requirements file is present
    $reqs = Get-ChildItem -Path $projDir -Filter "requirements*.txt" -Recurse -ErrorAction SilentlyContinue
    foreach ($req in $reqs) {
        Write-Host "    - installing from $($req.FullName)"
        & $pip install -r $req.FullName --quiet
    }
}

Write-Host ""
Write-Host "[OK] BugsInPy projects prepared: $($Projects -join ', ')" -ForegroundColor Green
Write-Host "Run a benchmark with:"
Write-Host "  python -m benchmarks --dataset bugsinpy --bugsinpy-root $($root.Path) --bugsinpy-projects $($Projects -join ' ') --limit 5"
