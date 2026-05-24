FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /simulator

COPY pyproject.toml .
RUN uv pip install --system -e "."

COPY . .

ENTRYPOINT ["python", "-m", "app.main"]
