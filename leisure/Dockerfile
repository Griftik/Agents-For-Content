# Контекст сборки — корень репозитория: docker build -f leisure/Dockerfile .
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY leisure/requirements.txt leisure/requirements.txt
RUN pip install -r leisure/requirements.txt
COPY leisure leisure
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)" || exit 1
# Секреты приходят только через окружение при запуске (.env в compose), в образ не попадают (.dockerignore).
CMD ["uvicorn", "leisure.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
