# Genera tráfico real contra el sistema para observarlo en Grafana.
# Uso:  .\scripts\generar-carga.ps1 -Clave "<ANALISTA_PASSWORD>" -Solicitudes 200
param(
    [string]$Base = "http://localhost:8080",
    [string]$Usuario = "analista",
    [Parameter(Mandatory = $true)][string]$Clave,
    [int]$Solicitudes = 200
)
$ErrorActionPreference = "Stop"
$login = Invoke-RestMethod -Method Post -Uri "$Base/api/v1/auth/login" `
    -Body @{ username = $Usuario; password = $Clave } -ContentType "application/x-www-form-urlencoded"
$h = @{ Authorization = "Bearer $($login.access_token)" }
$comunas = "Valparaíso", "Viña del Mar", "Quilpué", "Villa Alemana", "Concón", "Quillota", "Limache", "Casablanca", "San Antonio", "Los Andes"
$instancias = @{}
for ($i = 1; $i -le $Solicitudes; $i++) {
    $cuerpo = @{
        comuna    = $comunas | Get-Random
        variables = @{
            temperatura = Get-Random -Minimum 12 -Maximum 38; humedad = Get-Random -Minimum 10 -Maximum 90
            viento = Get-Random -Minimum 0 -Maximum 60; dias_sin_lluvia = Get-Random -Minimum 0 -Maximum 90
        }
    }
    # Cada 5 consultas se usa clima real (Open-Meteo, cacheado 10 min)
    if ($i % 5 -eq 0) { $cuerpo.Remove("variables") }
    try {
        $r = Invoke-RestMethod -Method Post -Uri "$Base/api/v1/riesgo" -Headers $h `
            -Body ([Text.Encoding]::UTF8.GetBytes(($cuerpo | ConvertTo-Json))) -ContentType "application/json; charset=utf-8"
        $instancias[$r.instancia_api]++
        Write-Host ("{0,4} {1,-14} {2,-8} ({3})" -f $i, $r.comuna, $r.nivel, $r.instancia_api)
    } catch { Write-Warning "$i -> $($_.Exception.Message)" }
}
# Solicitudes no autorizadas a propósito (deben verse como 401/403 en Grafana)
1..10 | ForEach-Object { try { Invoke-RestMethod "$Base/api/v1/alertas" -Headers $h } catch {} }
1..10 | ForEach-Object { try { Invoke-RestMethod "$Base/api/v1/consultas" } catch {} }
Write-Host "`nDistribución del balanceador:"; $instancias
