$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonCandidates = @()
if ($env:COGNITIVEOS_PYTHON) {
  $pythonCandidates += $env:COGNITIVEOS_PYTHON
}
if ($env:COGNITIVEOS_SEMANTIC_RUNTIME -eq "local") {
  $pythonCandidates += (Join-Path $repoRoot ".venv-embeddings312\Scripts\python.exe")
}
$pythonCandidates += @(
  "python",
  "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
  "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
  "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
)

$python = $null
foreach ($candidate in $pythonCandidates) {
  try {
    if ($candidate -eq "python") {
      $cmd = Get-Command python -ErrorAction Stop
      $probe = & $cmd.Source -c "print('ok')" 2>$null
      if ($LASTEXITCODE -eq 0 -and $probe -eq "ok") {
        $python = $cmd.Source
        break
      }
      continue
    }
    if (Test-Path $candidate) {
      $probe = & $candidate -c "print('ok')" 2>$null
      if ($LASTEXITCODE -eq 0 -and $probe -eq "ok") {
        $python = $candidate
        break
      }
    }
  } catch {
  }
}

if (-not $python) {
  Write-Error "No Python executable found for CognitiveOS MCP server."
  exit 1
}

$env:PYTHONPATH = Join-Path $repoRoot "src"
& $python -m cognitiveos.mcp_server --vault-root $repoRoot
