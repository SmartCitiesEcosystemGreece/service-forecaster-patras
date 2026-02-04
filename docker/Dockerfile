FROM python:3.11-slim
WORKDIR /usr/src/app

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential gcc libatlas-base-dev \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy everything (including .env and your API key file) into the image
COPY . .

EXPOSE 9013
CMD ["python", "app.py"]
