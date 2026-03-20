FROM python:3.11-slim
WORKDIR /app
ENV PYTHONPATH=/app
COPY services/gateway/requirements.txt /app/service/requirements.txt
RUN pip install --no-cache-dir -r /app/service/requirements.txt
COPY services/common /app/common
COPY services/gateway /app/service
WORKDIR /app/service
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "app.py"]
