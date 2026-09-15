FROM python:3.11-slim

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

# --upgrade ফ্ল্যাগ যোগ করা হয়েছে যাতে yt-dlp সর্বদা নতুন ভার্সন পায়
RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
