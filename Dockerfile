FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

# Install system dependencies needed for reportlab/pdf generation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy minimal bot requirements
COPY requirements-bot.txt .

# Install only bot dependencies
RUN pip install --no-cache-dir -r requirements-bot.txt

# Copy all source code
COPY . .

# Create and switch to non-root user
RUN useradd -m appuser
USER appuser

# Run the bot
CMD ["python", "-m", "src.bot.main"]
