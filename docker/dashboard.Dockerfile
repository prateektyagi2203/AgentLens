FROM node:22-slim
WORKDIR /app
RUN npm i -g pnpm
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/dashboard ./apps/dashboard
RUN pnpm install --frozen-lockfile --filter @agentlens/dashboard...
RUN pnpm --filter @agentlens/dashboard build
EXPOSE 3101
CMD ["pnpm", "--filter", "@agentlens/dashboard", "start"]
