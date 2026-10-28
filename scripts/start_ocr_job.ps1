param(
    [string]$Inventory = 'config/production-pages.json',
    [int]$Concurrency = 1
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv-gpu/Scripts/python.exe'
$Script = Join-Path $PSScriptRoot 'ocr_vl.py'
$Manifest = Join-Path $ProjectRoot $Inventory
if (-not (Test-Path -LiteralPath $Manifest)) { throw "Missing inventory: $Manifest" }
$Health = Invoke-RestMethod -Uri 'http://127.0.0.1:8111/health' -TimeoutSec 5
if ($Health.status -ne 'ok') { throw 'The local OCR server is not ready.' }
$LogRoot = Join-Path $ProjectRoot '.cache/ocr-job'
New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
$JobFile = Join-Path $LogRoot 'current.json'
if (Test-Path -LiteralPath $JobFile) {
    $OldJob = Get-Content -LiteralPath $JobFile -Raw | ConvertFrom-Json
    $OldProcess = Get-Process -Id $OldJob.process_id -ErrorAction SilentlyContinue
    if ($OldProcess -and $OldProcess.Path -eq $Python) {
        Write-Output "Existing OCR job PID $($OldJob.process_id), log $($OldJob.stdout)"
        exit 0
    }
}
$RunId = Get-Date -Format 'yyyyMMdd-HHmmss'
$Stdout = Join-Path $LogRoot "$RunId.stdout.log"
$Stderr = Join-Path $LogRoot "$RunId.stderr.log"
$env:NO_PROXY = '127.0.0.1,localhost'
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = 'True'
$Arguments = @('-u','-X','utf8',('"'+$Script+'"'),'--inventory',('"'+$Inventory+'"'),'--concurrency',$Concurrency)
$Process = Start-Process -FilePath $Python -ArgumentList $Arguments -WorkingDirectory $ProjectRoot -WindowStyle Hidden `
    -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr -PassThru
$Record = @{
    process_id=$Process.Id; inventory=$Manifest; stdout=$Stdout; stderr=$Stderr;
    started_at=(Get-Date).ToUniversalTime().ToString('o'); concurrency=$Concurrency;
    output_subdir='vl1.6'; review_status='unreviewed'
}
$Record | ConvertTo-Json | Set-Content -LiteralPath $JobFile -Encoding utf8
$Record | ConvertTo-Json
