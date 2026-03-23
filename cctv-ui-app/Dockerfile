FROM python:3.11-slim

# ---------------- SYSTEM DEPENDENCIES ----------------
RUN apt-get update && apt-get install -y \
    libegl1 libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    libportaudio2 libasound2 libxkbcommon-x11-0 libxcb-xinerama0 \
    libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
    libxcb-render-util0 libxcb-shape0 libxcb-xfixes0 libxcb-randr0 \
    libxcb-xinput0 libdbus-1-3 libfontconfig1 libfreetype6 libx11-6 \
    libx11-xcb1 libxcb1 libxi6 libxcomposite1 libxcursor1 libxdamage1 \
    libxfixes3 libxrandr2 libxtst6 ca-certificates \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# ---------------- PYTHON ----------------
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy assets folder
COPY assets ./assets

# Copy app code
COPY cctv-ui.py .

# ---------------- ENVIRONMENT ----------------
# Force X11 backend for PyQt6
ENV QT_QPA_PLATFORM=xcb
ENV QT_PLUGIN_PATH=/usr/local/lib/python3.11/site-packages/PyQt6/Qt6/plugins

# ---------------- RUN ----------------
CMD ["python", "cctv-ui.py"]

