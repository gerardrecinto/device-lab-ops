FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY examples ./examples
RUN pip install --no-cache-dir . && useradd -m lab && mkdir /data && chown lab /data
USER lab
ENV DEVICELAB_DB=/data/devicelab.db
EXPOSE 8080
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz')"
CMD ["sh", "-c", "devicelab --db $DEVICELAB_DB init --inventory examples/inventory.json && exec devicelab --db $DEVICELAB_DB serve --inventory examples/inventory.json --bind 0.0.0.0"]
