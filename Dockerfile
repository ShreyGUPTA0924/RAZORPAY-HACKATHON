FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY pipeline/ ./pipeline/
COPY surface/ ./surface/
COPY eval/ ./eval/
COPY api/ ./api/

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
