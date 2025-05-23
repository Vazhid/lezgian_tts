FROM python:3.10-slim

RUN pip install poetry

WORKDIR /app

COPY pyproject.toml poetry.lock* ./

RUN poetry install --no-root --no-interaction

COPY . .

EXPOSE 1010

CMD ["poetry", "run", "gunicorn", "--bind", "0.0.0.0:1010", "--timeout", "120", "app:app"]