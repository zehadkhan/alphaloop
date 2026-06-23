# Single-stage build — Coolify injects ~36 ARGs per stage; multi-stage (4×) often breaks npm.
FROM node:20-slim
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates wget \
    && rm -rf /var/lib/apt/lists/*

ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_OPTIONS=--max-old-space-size=2048
ENV PORT=3001
ENV HOSTNAME=0.0.0.0

# package.json only — avoid lockfile platform mismatches on the VPS builder
COPY package.json .npmrc ./

# Inline env beats Coolify-injected NODE_ENV=production build-args
RUN NODE_ENV=development NPM_CONFIG_PRODUCTION=false npm install --no-audit --no-fund --legacy-peer-deps

COPY . .

RUN NODE_ENV=development NPM_CONFIG_PRODUCTION=false npm run build \
    && cp -r .next/static .next/standalone/.next/static

ENV NODE_ENV=production

EXPOSE 3001

HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 \
  CMD wget -qO /dev/null http://localhost:3001/ || exit 1

CMD ["node", ".next/standalone/server.js"]
