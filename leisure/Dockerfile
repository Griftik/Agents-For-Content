# Контекст сборки — корень репозитория: docker build -f leisure/Dockerfile .
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY leisure/requirements.txt leisure/requirements.txt
RUN pip install -r leisure/requirements.txt
COPY leisure leisure
EXPOSE 8000
CMD ["uvicorn", "leisure.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
