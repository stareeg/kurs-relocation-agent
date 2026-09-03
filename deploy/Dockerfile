# Контекст сборки — корень репо (deploy/compose.yaml: context ".."). Нужны pyproject.toml + uv.lock + пакеты.
# Плоская раскладка: пакеты core/ api/ bot_app/ импортируются через PYTHONPATH=/app (без install).
#
# Этап 1 (ext-build): собирает extension/dist, чтобы /api/meta/extension/download не отдавал 409.
# EXT_API_BASE_URL — прод-домен на момент сборки .zip; без него в бандл подставляется
# localhost:8000 (дефолт, extension/build.mjs).
# Раскладка как в репо: extension/src бандлит shared/ (../../../shared/*) и дефолтные JSON'ы
# из ../../../core/domains/opportunities/sources/ (hh_selectors.json, extension_runtime_config.json).
FROM node:24-alpine AS ext-build
WORKDIR /build
COPY extension/package.json extension/package-lock.json extension/
RUN cd extension && npm ci
COPY extension/ extension/
COPY shared/ shared/
# *.json, не отдельные файлы — новый бандлимый JSON не должен ронять docker build (инцидент
# 2026-08-28: extension_runtime_config.json забыли добавить, esbuild «Could not resolve»).
COPY core/domains/opportunities/sources/*.json core/domains/opportunities/sources/
ARG EXT_API_BASE_URL=""
ENV EXT_API_BASE_URL=${EXT_API_BASE_URL}
# build:ext:ci — без prebuild:ext (npm test): часть тестов читает больше core/, чем этот
# один JSON (skip-reasons.test.ts). Тесты расширения гоняются отдельно в CI (§7.3).
RUN cd extension && npm run build:ext:ci

# Этап 2: API-образ. Копируем только ship-набор расширения (без node_modules/src/tests) —
# build_extension_zip читает ровно эти файлы (core/repo/extension_bundle.py).
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONPATH=/app
# Коммит, из которого собран образ — читает лог-бандл (core/platform/repo/log_bundle.py) и
# версия FastAPI-приложения (api/main.py); без сборочного аргумента остаётся пустой строкой,
# бандл честно покажет git_sha=null вместо угадывания.
ARG GIT_SHA=""
ENV COPILOT_GIT_SHA=${GIT_SHA}

# Слой зависимостей: только манифесты, кэшируется пока не меняются версии
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Код: плоские пакеты + миграции (внутри core/platform/db/migrations)
COPY core/ core/
COPY api/ api/
COPY bot_app/ bot_app/

# Промпты: пути в core/domains/*/llm.py резолвятся относительно CWD (/app) в рантайме, не только
# на этапе сборки — без этого слоя каждый LLM-вызов падает FileNotFoundError (был баг, .dockerignore
# по ошибке резал prompts/ вместе с dev-only plans/resume/docs, docs/problems.md 2026-08-05).
COPY prompts/ prompts/

# Расширение: ship-набор из предыдущего этапа (dist/, icons/, manifest.json, options.html, popup.html).
# manifest.json берём из ext-build, а не из контекста: build.mjs переписывает его при
# EXT_API_BASE_URL (host_permissions[0] → прод-домен), контекстная копия эту подстановку потеряет.
COPY --from=ext-build /build/extension/dist/ extension/dist/
COPY --from=ext-build /build/extension/manifest.json extension/manifest.json
COPY extension/icons/ extension/icons/
COPY extension/options.html extension/popup.html extension/

EXPOSE 8000
# Ровно один воркер — без --workers и без WEB_CONCURRENCY. «Мультиплеер» держит хаб живых
# столов и WS-партии в памяти процесса (core/domains/multiplayer/session.py::_HUB): с
# несколькими воркерами WS-соединение попадёт не в тот процесс, и стол будет «то работать, то
# нет». Инвариант Э20.5, разбор — core/domains/multiplayer/README.md, раздел «Один воркер».
# api/main.py на старте пишет ERROR в журнал, если воркеров больше одного.
CMD ["uv", "run", "--no-sync", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
