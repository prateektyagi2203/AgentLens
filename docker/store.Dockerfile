FROM node:22-slim
WORKDIR /app
RUN npm i -g pnpm
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/store ./apps/store
RUN pnpm install --frozen-lockfile --filter @agentlens/store...
RUN pnpm --filter @agentlens/store build
EXPOSE 3100
CMD ["pnpm", "--filter", "@agentlens/store", "start"]
