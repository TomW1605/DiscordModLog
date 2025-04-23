# Use the official Python image from the Docker Hub
FROM python:3.12
LABEL authors="Thomas White"

# Install dependencies
RUN pip3 install discord.py sqlalchemy pyaml

# Create and set the working directory
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Create the config directory for the database file
RUN mkdir -p /config

# Run the command to start the Flask application
CMD ["python", "-u", "ModLogBot.py"]
