FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml .
RUN uv pip install --system -e "."

COPY . .

# Train models at build time if checkpoints are absent.
# When saved_models/ is present (host-trained), this is a no-op.
RUN if [ ! -f saved_models/lstm_v1.pt ] || [ ! -f saved_models/anomaly_v1.pkl ]; then \
        echo "=== ML checkpoints missing — training fresh models ===" && \
        python -m training.generate_dataset && \
        python -m training.train_anomaly && \
        python -m training.train_lstm; \
    else \
        echo "=== ML checkpoints present, skipping training ==="; \
        ls -la saved_models/; \
    fi

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
