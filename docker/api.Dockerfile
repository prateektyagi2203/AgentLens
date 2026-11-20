FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml README.md ./
COPY services ./services
COPY config ./config
RUN uv pip install --system -e .
EXPOSE 8100
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8100/health', timeout=4)" || exit 1
CMD ["uvicorn", "agentlens.main:app", "--host", "0.0.0.0", "--port", "8100"]
