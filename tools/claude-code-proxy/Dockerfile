FROM python:3.11-slim

WORKDIR /claude-code-proxy

# Copy package specifications
COPY pyproject.toml uv.lock ./

RUN pip install --upgrade uv && uv sync

# Copy project code to current directory
COPY . .

# Start the proxy
EXPOSE 8082
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8082/health', timeout=5).status == 200 else 1)"]
CMD uv run uvicorn server:app --host 0.0.0.0 --port 8082 --reload
