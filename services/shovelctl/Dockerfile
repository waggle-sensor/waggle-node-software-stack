FROM python:3-alpine

RUN pip3 install --no-cache-dir requests

WORKDIR /app
COPY . .
ENTRYPOINT ["python3", "/app/shovelctl.py"]
