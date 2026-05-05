# Defects4J setup script for Windows / PowerShell.
#
# Defects4J is a Java-bug benchmark used for empirical evaluation of program
# repair systems. It needs:
#   - Java 8 (NOT Java 17+; the build scripts assume Java 8)
#   - Perl 5.10+ with the cpanm package manager
#   - Git
#   - SVN (optional, only some old projects need it)
#
# This script checks the prerequisites, fetches Perl deps, and runs Defects4J's
# own ./init.sh. Expect it to take 30-90 minutes on a fresh machine and
# require several GB of disk + network bandwidth.

param(
    [string]$Defects4JRoot = "$PSScriptRoot\..\data\bug_datasets\defects4j"
)

$ErrorActionPreference = "Stop"

function Require-Command($name, $hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        Write-Error "[setup_defects4j] missing required command: $name. $hint"
    }
}

Write-Host "==> Checking prerequisites..." -ForegroundColor Cyan
Require-Command "git" "Install Git for Windows: https://git-scm.com/download/win"
Require-Command "perl" "Install Strawberry Perl: https://strawberryperl.com/"
Require-Command "java" "Install Java 8 (Eclipse Temurin 8 recommended)."

# Verify Java 8 specifically
$javaVersion = (& java -version 2>&1) -join " "
if ($javaVersion -notmatch '"1\.8|"8\.') {
    Write-Warning "Java 8 not detected. Defects4J will likely fail with newer Java."
    Write-Warning "Detected: $javaVersion"
    Write-Warning "Set JAVA_HOME to a JDK 8 install before continuing."
}

# Resolve and create the target directory
$root = Resolve-Path -LiteralPath $Defects4JRoot -ErrorAction SilentlyContinue
if (-not $root) {
    Write-Host "==> $Defects4JRoot not found; cloning Defects4J..." -ForegroundColor Cyan
    $parent = Split-Path -Parent $Defects4JRoot
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    git clone https://github.com/rjust/defects4j $Defects4JRoot
    $root = Resolve-Path -LiteralPath $Defects4JRoot
}

Push-Location $root.Path
try {
    Write-Host "==> Installing Perl dependencies (cpanm --installdeps)..." -ForegroundColor Cyan
    if (-not (Get-Command cpanm -ErrorAction SilentlyContinue)) {
        Write-Host "Installing cpanminus..."
        cpan App::cpanminus
    }
    cpanm --installdeps . --notest

    Write-Host "==> Running Defects4J init.sh (downloads project sources)..." -ForegroundColor Cyan
    if (Get-Command bash -ErrorAction SilentlyContinue) {
        bash ./init.sh
    } else {
        Write-Warning "bash not found. Run ./init.sh from a Git Bash / WSL shell yourself."
    }

    Write-Host "==> Adding Defects4J framework/bin to PATH for this session..." -ForegroundColor Cyan
    $env:PATH = "$($root.Path)\framework\bin;$env:PATH"

    # Smoke test
    Write-Host "==> Smoke test..." -ForegroundColor Cyan
    & defects4j info -p Lang
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Defects4J smoke test failed."
    } else {
        Write-Host "[OK] Defects4J is ready." -ForegroundColor Green
        Write-Host ""
        Write-Host "Next steps:"
        Write-Host "  1. Add this to your shell profile to keep defects4j on PATH:"
        Write-Host "     `$env:PATH = `"$($root.Path)\framework\bin;`$env:PATH`""
        Write-Host "  2. Run: python -m benchmarks --dataset defects4j --defects4j-project Lang --limit 5"
    }
} finally {
    Pop-Location
}
