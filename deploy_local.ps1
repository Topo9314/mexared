<#
.SYNOPSIS
    Automatiza el push de cambios locales a GitHub (Proyecto MEXARED).

.DESCRIPTION
    ▸ Cambia al directorio del proyecto.
    ▸ Realiza git pull (para evitar fast-forward errors).
    ▸ Hace stage de todos los cambios.
    ▸ Crea el commit (mensaje como argumento o por prompt).
    ▸ Hace push a origin/master.
    ▸ Muestra errores claros y devuelve código de salida coherente.
#>

param (
    [string]$CommitMessage  # Permite: .\deploy_local.ps1 "mensaje de commit"
)

# ─── CONFIGURACIÓN ─────────────────────────────────────────────────────────────
$ProjectPath   = "C:\Users\campo\OneDrive\Escritorio\MEXARED"
$RemoteName    = "origin"
$RemoteBranch  = "master"
# ───────────────────────────────────────────────────────────────────────────────

function Abort($Msg) {
    Write-Host "[ERROR] $Msg" -ForegroundColor Red
    exit 1
}

# 1. Verificaciones previas -----------------------------------------------------
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Abort "Git no está instalado o no está en el PATH."
}

if (-not (Test-Path $ProjectPath)) {
    Abort "La ruta del proyecto '$ProjectPath' no existe."
}

Write-Host "[INFO] Cambiando al proyecto: $ProjectPath"
Set-Location $ProjectPath

# 2. Sincronizar con remoto antes de commitear ----------------------------------
Write-Host "[INFO] Sincronizando con $RemoteName/$RemoteBranch..."
git pull $RemoteName $RemoteBranch
if ($LASTEXITCODE -ne 0) { Abort "Falló 'git pull'. Revisa conflictos o conexión." }

# 3. Stage de todos los archivos ------------------------------------------------
Write-Host "[INFO] Añadiendo cambios..."
git add -A
if ($LASTEXITCODE -ne 0) { Abort "Falló 'git add'." }

# 4. Preparar mensaje de commit -------------------------------------------------
if (-not $CommitMessage) {
    $CommitMessage = Read-Host "[INPUT] Mensaje del commit (vacío = cancelar)"
    if (-not $CommitMessage) { Abort "Commit cancelado por el usuario." }
}

Write-Host "[INFO] Creando commit..."
git commit -m "$CommitMessage"
switch ($LASTEXITCODE) {
    0 { }  # commit ok
    1 { Write-Host "[INFO] No hay cambios para commitear." -ForegroundColor Yellow }
    default { Abort "Falló 'git commit' (código $LASTEXITCODE)." }
}

# 5. Push al remoto -------------------------------------------------------------
Write-Host "[INFO] Haciendo push a $RemoteName/$RemoteBranch..."
git push $RemoteName $RemoteBranch
if ($LASTEXITCODE -ne 0) { Abort "Falló 'git push'. Verifica credenciales o conflictos remotos." }

Write-Host "[SUCCESS] Cambios enviados correctamente a GitHub." -ForegroundColor Green
exit 0
