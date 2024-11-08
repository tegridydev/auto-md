FROM python:3.12

WORKDIR /app

RUN apt-get update && apt-get install -y \
    git libmagic-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "wsgi.py"]