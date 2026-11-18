FROM node:22-slim
WORKDIR /app
RUN npm i -g pnpm
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/dashboard ./apps/dashboard
RUN pnpm install --frozen-lockfile --filter @agentlens/dashboard...
# NEXT_PUBLIC_* values are inlined at build time, so the API URL (as seen from the browser) is a build arg.
ARG NEXT_PUBLIC_API_URL=http://localhost:8100/api
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN pnpm --filter @agentlens/dashboard build
EXPOSE 3101
CMD ["pnpm", "--filter", "@agentlens/dashboard", "start"]
