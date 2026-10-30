FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY blackout ./blackout
RUN pip install --no-cache-dir . && useradd --create-home --uid 10001 lab && mkdir /data && chown lab:lab /data
USER lab
ENV BLACKOUT_DATA_DIR=/data
EXPOSE 8080
CMD ["python", "-m", "blackout", "serve", "--host", "0.0.0.0", "--port", "8080"]
