FROM node:22-slim
WORKDIR /app
RUN npm i -g pnpm
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/dashboard ./apps/dashboard
RUN pnpm install --frozen-lockfile --filter @agentlens/dashboard...
# NEXT_PUBLIC_* values are inlined at build time, so the API URL (as seen from the browser) is a build arg.
ARG NEXT_PUBLIC_API_URL=http://localhost:8100/api
ARG NEXT_PUBLIC_SITE_URL=
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_PUBLIC_SITE_URL=$NEXT_PUBLIC_SITE_URL
RUN pnpm --filter @agentlens/dashboard build
RUN chown -R node:node /app
USER node
EXPOSE 3101
ENV NODE_ENV=production
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3101/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["pnpm", "--filter", "@agentlens/dashboard", "start"]
