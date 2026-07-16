FROM python:3.12-slim
RUN pip install --no-cache-dir "mcp>=1.9" "uvicorn>=0.30"
COPY app.py /app/app.py
WORKDIR /app
EXPOSE 9100
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "9100"]
