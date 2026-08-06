FROM node:24-alpine AS deps
WORKDIR /app
COPY apps/web/package.json ./
RUN npm install

FROM node:24-alpine AS build
WORKDIR /app
# Rewrite targets for Next.js /api proxy. Overridden via compose build args
# to the Docker-network service names (api:8000 / ai:8001). Local dev keeps
# the localhost defaults so `npm run dev` works outside Docker.
ARG API_URL=http://localhost:8000
ARG AI_URL=http://localhost:8001
ENV API_URL=$API_URL
ENV AI_URL=$AI_URL
COPY --from=deps /app/node_modules ./node_modules
COPY apps/web/ .
RUN npm run build

FROM node:24-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
COPY --from=build /app/package.json ./package.json
COPY --from=deps /app/node_modules ./node_modules
COPY --from=build /app/next.config.ts ./
COPY --from=build /app/tsconfig.json ./

EXPOSE 3000
CMD ["npm", "start"]
