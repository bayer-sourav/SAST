FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

COPY integrations/github/requirements.txt /tmp/github-reqs.txt
RUN pip install --no-cache-dir -r /tmp/github-reqs.txt

COPY integrations/ /app/integrations/
COPY services/ /app/services/
COPY benchmark/ /app/benchmark/
COPY core/ /app/core/
COPY models/ /app/models/
COPY timing.py /app/timing.py

ENV PYTHONPATH=/app
ENV SAST_ROOT=/app

EXPOSE 8080 8090

CMD ["uvicorn", "integrations.github.app.webhook_server:app", "--host", "0.0.0.0", "--port", "8080"]
