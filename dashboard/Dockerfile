FROM node:20-slim AS base
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates wget \
    && rm -rf /var/lib/apt/lists/*

# ── Stage 1: install dependencies ───────────────────────────────────────────
FROM base AS deps
# Coolify injects build-args (often NODE_ENV=production) — force dev deps for build.
ENV NODE_ENV=development
ENV NPM_CONFIG_PRODUCTION=false
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# ── Stage 2: build ──────────────────────────────────────────────────────────
FROM base AS builder
ENV NODE_ENV=development
ENV NPM_CONFIG_PRODUCTION=false
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_OPTIONS=--max-old-space-size=2048
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# ── Stage 3: production runner ──────────────────────────────────────────────
FROM base AS runner
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3001
ENV HOSTNAME=0.0.0.0

COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next

EXPOSE 3001

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD wget -qO /dev/null http://localhost:3001/ || exit 1

CMD ["node_modules/.bin/next", "start"]
