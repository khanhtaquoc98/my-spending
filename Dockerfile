# Use explicit debian release
FROM python:3.10-slim-bookworm

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=5000
ENV DEBIAN_FRONTEND=noninteractive

# Install Tesseract OCR and Vietnamese language data, plus OpenCV required libs
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-vie \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt /app/
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . /app/

# Expose the port
EXPOSE 5000

# Run the application with Gunicorn
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "--timeout", "120", "app:app"]
