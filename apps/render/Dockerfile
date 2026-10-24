# Build context: repo root (see infra/docker-compose.yml)
FROM node:20-slim AS base
RUN corepack enable
WORKDIR /app

# System libraries required by the Chromium that Remotion drives
RUN apt-get update && apt-get install -y --no-install-recommends \
      libnss3 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 libasound2 libxrandr2 \
      libxkbcommon0 libxfixes3 libxcomposite1 libxdamage1 libgbm1 libcups2 \
      libpango-1.0-0 libcairo2 libxshmfence1 fonts-liberation ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Dependency layer: only manifests, so it is cached until a dependency changes
FROM base AS deps
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY packages/script-schema/package.json packages/script-schema/
COPY apps/render/package.json apps/render/
COPY apps/web/package.json apps/web/
RUN pnpm install --frozen-lockfile --filter render...

FROM base AS runtime
ENV NODE_ENV=production
COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/apps/render/node_modules ./apps/render/node_modules
COPY package.json pnpm-workspace.yaml ./
COPY apps/render ./apps/render
# Root.tsx imports the sample script when bundling
COPY packages/script-schema/examples ./packages/script-schema/examples
WORKDIR /app/apps/render

EXPOSE 3001
CMD ["pnpm", "start"]
