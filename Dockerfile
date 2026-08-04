# CityOS / Missions — FastAPI backend that also serves the single-file frontend.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# Install Python deps first for better layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App code (backend serves ../frontend at "/")
COPY backend/ ./backend/
COPY frontend/ ./frontend/

EXPOSE 8000

# main.py reads PORT from the environment and binds 0.0.0.0
CMD ["python", "backend/main.py"]
