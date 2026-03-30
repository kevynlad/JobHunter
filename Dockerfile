FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

# Install system dependencies needed for reportlab/pdf generation and gosu for dropping privileges
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Copy minimal bot requirements
COPY requirements-bot.txt .

# Install only bot dependencies
RUN pip install --no-cache-dir -r requirements-bot.txt

# Create the non-root user
RUN useradd -m appuser

# Copy all source code
COPY . .

# Fix Windows CRLF line endings to Linux LF, and ensure script is executable
RUN sed -i 's/\r$//' entrypoint.sh && chmod +x entrypoint.sh

# The entrypoint script will chown the /app/data volume and switch to appuser
ENTRYPOINT ["./entrypoint.sh"]

# Expected to receive CMD from railway.toml or default here
CMD ["python", "-m", "src.bot.main"]
