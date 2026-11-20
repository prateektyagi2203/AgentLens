FROM node:22-slim
WORKDIR /app
RUN npm i -g pnpm
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/store ./apps/store
RUN pnpm install --frozen-lockfile --filter @agentlens/store...
RUN pnpm --filter @agentlens/store build
RUN mkdir -p /app/data && chown -R node:node /app
USER node
EXPOSE 3100
ENV HOST=0.0.0.0 NODE_ENV=production
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3100/robots.txt').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["pnpm", "--filter", "@agentlens/store", "start"]
