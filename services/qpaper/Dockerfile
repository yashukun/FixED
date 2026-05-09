FROM python:3.11-slim
# Install uv
RUN pip install uv

WORKDIR /app

# Copy only requirements first (for caching)
COPY services/qpaper/requirements.txt .

# Install dependencies (FAST ⚡)
RUN uv pip install --system -r requirements.txt
COPY services/qpaper .
COPY services/shared shared
ENV PYTHONPATH="/app:/app/shared"
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]