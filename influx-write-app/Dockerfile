# Use a lightweight official Python 3.11 base image
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Copy all files from the current directory on the host into the container
COPY . .

# Install Python dependencies listed in requirements.txt without caching to reduce image size
RUN pip install --no-cache-dir -r requirements.txt

# Make the start script executable
RUN chmod +x start.sh

# Define the default command to run when the container starts
# Start.sh consists of both vibration-influx write.py and energy-influx-write.py
CMD ["./start.sh"]
