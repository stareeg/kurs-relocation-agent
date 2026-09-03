<#
  test_repo_docker.ps1 - прогон pytest с реальной БД внутри compose-сети.

  asyncpg с Windows-хоста не ходит в проброшенный Docker-порт (docs/problems.md 1.1),
  поэтому тесты с фикстурами pg_pool на хосте скипаются. Здесь гоняем pytest в
  одноразовом контейнере на сети copilot_default: Postgres виден как хост postgres,
  поэтому DB-тесты реально выполняются, а не скипаются.

  Образ - тот же uv, что и api (python3.13). Зависимости ставятся в именованный том
  copilot_pytest_venv (а кэш uv - в copilot_uv_cache), поэтому ПЕРВЫЙ запуск тянет образ
  и ставит пакеты несколько минут, дальше .venv переиспользуется и прогон быстрый.

  По умолчанию - весь suite (-q). Доп. аргументы уходят в pytest:
      .\deploy\test_repo_docker.ps1 -k repo
      .\deploy\test_repo_docker.ps1 tests/test_repo.py -q
#>
[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $PytestArgs)

# НЕ Stop: docker/compose штатно пишут прогресс в stderr, а PS 5.1 оборачивает это в
# NativeCommandError и под Stop роняет скрипт ещё до контейнера. Реальные сбои ловим
# по $LASTEXITCODE (нативный exit code), а не по записи в stderr.
$ErrorActionPreference = "Continue"
$repo = (Get-Location).Path

if (-not $PytestArgs -or $PytestArgs.Count -eq 0) {
    $PytestArgs = @("-q")
}
$pytest = ($PytestArgs -join " ")

Write-Host "[docker] поднимаю postgres (idempotent)..."
docker compose -f deploy/compose.yaml up -d postgres
if ($LASTEXITCODE -ne 0) { throw "docker compose up упал (exit $LASTEXITCODE) - запущен ли Docker Desktop?" }

Write-Host "[docker] pytest в сети copilot_default: python -m pytest $pytest"
$dockerArgs = @(
    "run", "--rm",
    "--network", "copilot_default",
    "-v", "${repo}:/app",
    "-v", "copilot_pytest_venv:/app/.venv",
    "-v", "copilot_uv_cache:/root/.cache/uv",
    "-w", "/app",
    "-e", "POSTGRES_HOST=postgres",
    # Внутри docker-сети PG слушает 5432; перебиваем POSTGRES_PORT из .env (dev там 5432 для нативной
    # PG), чтобы asyncpg в контейнере шёл на postgres:5432, а фикстуры pg_pool не скипались.
    "-e", "POSTGRES_PORT=5432",
    "-e", "PYTHONUTF8=1",
    "-e", "PYTHONIOENCODING=utf-8",
    "-e", "UV_LINK_MODE=copy",
    "ghcr.io/astral-sh/uv:python3.13-bookworm-slim",
    "bash", "-c", "uv sync --frozen && uv run --no-sync python -m pytest $pytest"
)
docker @dockerArgs
$code = $LASTEXITCODE

Write-Host "[docker] pytest exit code: $code"
exit $code
