FROM python:3.11-slim

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .

# Create logs directory
RUN mkdir -p logs

# Expose the application port (default is 7777)
EXPOSE 7777

# Run the application
CMD ["python", "main.py"]
