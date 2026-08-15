FROM node:24-alpine AS deps
WORKDIR /app
COPY apps/web/package.json ./
RUN npm install

# Production-only node_modules (no Vitest/TypeScript/etc.) for the runtime
# image — built separately from `deps` so the dev dependency tree used to
# build never ships in the final container.
FROM node:24-alpine AS prod-deps
WORKDIR /app
COPY apps/web/package.json ./
RUN npm install --omit=dev

FROM node:24-alpine AS build
WORKDIR /app
# Rewrite targets for Next.js /api proxy. Overridden via compose build args
# to the Docker-network service names (api:8000 / ai:8001). Local dev keeps
# the localhost defaults so `npm run dev` works outside Docker.
ARG API_URL=http://localhost:8000
ARG AI_URL=http://localhost:8001
ENV API_URL=$API_URL
ENV AI_URL=$AI_URL
# NEXT_PUBLIC_* vars are inlined into the client bundle at build time — a
# runtime `environment:` entry in docker-compose has no effect on them, so
# they must be passed as build args here (unlike API_URL/AI_URL above, which
# are only read server-side by next.config.ts's proxy rewrites).
ARG NEXT_PUBLIC_API_URL=http://localhost/api/v1
ARG NEXT_PUBLIC_WS_URL=ws://localhost/ws
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL
COPY --from=deps /app/node_modules ./node_modules
COPY apps/web/ .
RUN npm run build

FROM node:24-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
COPY --from=build /app/package.json ./package.json
COPY --from=prod-deps /app/node_modules ./node_modules
COPY --from=build /app/next.config.ts ./
COPY --from=build /app/tsconfig.json ./

EXPOSE 3000
CMD ["npm", "start"]
