# Контекст сборки — корень репо (deploy/compose.yaml: context "..", как у api/deploy/Dockerfile).
# frontend/src импортирует общие TS-модули из корневого shared/ (../../../../shared/*, тот же
# источник, что extension/src) — контекст ../frontend этого не видел, сборка падала на
# `npm run build` (TS2307).
# Этап 1: сборка SPA (schema.d.ts уже закоммичен, gen-api в образе не гоняем).
FROM node:24-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
COPY shared/ /shared/
RUN npm run build

# Этап 2: раздача статики + SSE-дружелюбный прокси на api (в dev-compose).
# В прод статику отдаёт внешний nginx (Фаза 6), этот слой — самодостаточный dev-вариант.
FROM nginx:alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
