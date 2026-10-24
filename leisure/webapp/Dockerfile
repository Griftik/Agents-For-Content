# Сборка из корня leisure/:  docker build -f webapp/Dockerfile .   (в compose это уже настроено)
# Контекст — leisure/, потому что текст /policy берётся из web/POLICY.md.
FROM node:22-alpine AS deps
WORKDIR /app/webapp
COPY webapp/package.json webapp/package-lock.json ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app/webapp
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/webapp/node_modules ./node_modules
COPY webapp/ ./
COPY web/POLICY.md /app/web/POLICY.md
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -S app && adduser -S app -G app
COPY --from=build --chown=app:app /app/webapp/.next/standalone ./
COPY --from=build --chown=app:app /app/webapp/.next/static ./.next/static
COPY --from=build --chown=app:app /app/webapp/content ./content
USER app
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s CMD wget -qO- http://127.0.0.1:3000/api/health >/dev/null || exit 1
# Секреты (API_KEY, LEISURE_BOT_TOKEN) приходят только через окружение при запуске, в образ не попадают.
CMD ["node", "server.js"]
