<<<<<<< HEAD
# Dockerfile content:
# Use a slim version of Python 3.11 for a smaller image
FROM python:3.11-slim

# Install system dependencies: ffmpeg (for audio) and libopus-dev (for discord.py audio)
RUN apt-get update && \
    apt-get install -y ffmpeg libopus-dev && \
    rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container
WORKDIR /app

# Copy requirements file and install python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Command to run your bot using the main file name
# IMPORTANT: Replace "your_bot_file_name.py" with the actual name of your Python file.
=======
# Dockerfile content:
# Use a slim version of Python 3.11 for a smaller image
FROM python:3.11-slim

# Install system dependencies: ffmpeg (for audio) and libopus-dev (for discord.py audio)
RUN apt-get update && \
    apt-get install -y ffmpeg libopus-dev && \
    rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container
WORKDIR /app

# Copy requirements file and install python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Command to run your bot using the main file name
# IMPORTANT: Replace "your_bot_file_name.py" with the actual name of your Python file.
>>>>>>> a71fac0cdd5bda2efb209374bf71547b0eaeaac3
CMD ["python", "Tune_Turtle_Bot.py"]