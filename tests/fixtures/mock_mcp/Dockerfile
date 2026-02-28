# Mock MCP Server Dockerfile
# Provides a simple HTTP server that returns canned MCP responses

FROM python:3.12-slim

WORKDIR /app

# Copy server files
COPY server.py .
COPY responses.json .

# Install curl for healthcheck
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Expose HTTP port
EXPOSE 8080

# Health check endpoint
HEALTHCHECK --interval=5s --timeout=3s --retries=5 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run in HTTP mode
CMD ["python", "server.py", "--http", "--port", "8080"]
