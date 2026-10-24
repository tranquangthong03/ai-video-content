# Build context: repo root (see infra/docker-compose.yml)
FROM node:20-slim AS base
RUN corepack enable
WORKDIR /app

# Dependency layer: only manifests, so it is cached until a dependency changes
FROM base AS deps
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY packages/script-schema/package.json packages/script-schema/
COPY apps/render/package.json apps/render/
COPY apps/web/package.json apps/web/
RUN pnpm install --frozen-lockfile --filter web...

FROM deps AS build
COPY apps/web ./apps/web
WORKDIR /app/apps/web
RUN pnpm build

FROM base AS runtime
ENV NODE_ENV=production
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/apps/web ./apps/web
COPY package.json pnpm-workspace.yaml ./
WORKDIR /app/apps/web

EXPOSE 3000
CMD ["pnpm", "start"]
