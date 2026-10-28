param([int]$Port = 8111, [int]$Parallel = 1, [int]$ContextSize = 4096)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RuntimeRoot = Join-Path $ProjectRoot '.tools/llama-b11829'
$ModelRoot = Join-Path $env:LOCALAPPDATA 'TextbookWorkbook/models/paddleocr-vl-1.6'
$Server = Get-ChildItem -LiteralPath $RuntimeRoot -Filter 'llama-server.exe' -Recurse | Select-Object -First 1
if (-not $Server) { throw 'Run scripts/download_ocr_runtime.py first.' }
$Model = Join-Path $ModelRoot 'PaddleOCR-VL-1.6-GGUF.gguf'
$Projector = Join-Path $ModelRoot 'PaddleOCR-VL-1.6-GGUF-mmproj.gguf'
if (-not (Test-Path -LiteralPath $Model) -or -not (Test-Path -LiteralPath $Projector)) {
    throw 'The official PaddleOCR-VL model download is incomplete.'
}
$LogRoot = Join-Path $ProjectRoot '.cache/ocr-server'
New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
$PidFile = Join-Path $LogRoot 'server.pid'
if (Test-Path -LiteralPath $PidFile) {
    $OldPid = [int](Get-Content -LiteralPath $PidFile)
    $OldProcess = Get-Process -Id $OldPid -ErrorAction SilentlyContinue
    if ($OldProcess -and $OldProcess.Path -eq $Server.FullName) {
        Write-Output "Existing PaddleOCR-VL server PID $OldPid"
        exit 0
    }
}
$Arguments = @(
    '-m', ('"' + $Model + '"'),
    '--mmproj', ('"' + $Projector + '"'),
    '--alias', 'PaddleOCR-VL-1.6',
    '--host', '127.0.0.1', '--port', $Port,
    '--ctx-size', $ContextSize, '--parallel', $Parallel,
    '--batch-size', '512', '--ubatch-size', '128',
    '--gpu-layers', '99', '--threads', '8', '--temp', '0'
)
$Process = Start-Process -FilePath $Server.FullName -ArgumentList $Arguments -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $LogRoot 'stdout.log') `
    -RedirectStandardError (Join-Path $LogRoot 'stderr.log') -PassThru
$Process.Id | Set-Content -LiteralPath $PidFile
Write-Output "PaddleOCR-VL server PID $($Process.Id), http://127.0.0.1:$Port"
