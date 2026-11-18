FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml README.md ./
COPY services ./services
COPY config ./config
RUN uv pip install --system -e .
EXPOSE 8100
CMD ["uvicorn", "agentlens.main:app", "--host", "0.0.0.0", "--port", "8100"]
