# Локальный деплой в обход GitHub Actions (инцидент / zombie queued).
# Требует: secrets/id_ed25519, SSH к DEPLOY_HOST.
#
#   .\deploy\deploy_prod.ps1
#   .\deploy\deploy_prod.ps1 -DeployHost <ip-или-домен-ВМ>
#
# Отменить зависший Actions Deploy (если runner ещё жив):
#   gh run list --workflow=deploy.yml --status=queued
#   gh run cancel <id>
#   gh workflow run deploy.yml   # или снова этот скрипт

param(
    [string]$DeployHost = $(if ($env:DEPLOY_HOST) { $env:DEPLOY_HOST } else { throw "Укажите DEPLOY_HOST или -DeployHost" }),
    [string]$User = $(if ($env:DEPLOY_USER) { $env:DEPLOY_USER } else { "deploy" }),
    [string]$Key = $(if ($env:DEPLOY_SSH_KEY) { $env:DEPLOY_SSH_KEY } else { "secrets/id_ed25519" }),
    [int]$Port = $(if ($env:DEPLOY_PORT) { [int]$env:DEPLOY_PORT } else { 22 })
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$keyPath = Join-Path $root $Key
if (-not (Test-Path $keyPath)) {
    throw "SSH key not found: $keyPath"
}

$scriptPath = Join-Path $PSScriptRoot "remote_up.sh"
if (-not (Test-Path $scriptPath)) {
    throw "Missing $scriptPath"
}

Write-Host "deploy_prod: $User@${DeployHost}:$Port (script remote_up.sh)"
# scp + bash file, не `bash -s`: иначе любой remote-команде со stdin
# (compose run без -T) съедает хвост скрипта.
$remoteTmp = "/tmp/copilot_remote_up.sh"
scp -i $keyPath -P $Port -o StrictHostKeyChecking=accept-new $scriptPath "${User}@${DeployHost}:${remoteTmp}"
if ($LASTEXITCODE -ne 0) {
    throw "deploy_prod: scp failed (exit $LASTEXITCODE)"
}
ssh -i $keyPath -p $Port -o StrictHostKeyChecking=accept-new "${User}@${DeployHost}" "bash $remoteTmp; ec=`$?; rm -f $remoteTmp; exit `$ec"
if ($LASTEXITCODE -ne 0) {
    throw "deploy_prod: remote failed (exit $LASTEXITCODE)"
}
Write-Host "deploy_prod: done"
