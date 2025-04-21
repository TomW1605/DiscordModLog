# Use the official Python image from the Docker Hub
FROM python:3.10
LABEL authors="Thomas White"

# Install dependencies
RUN pip3 install aiohttp==3.8.2
#RUN pip3 install discord.py
RUN pip3 install sqlalchemy

# Create and set the working directory
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Create the config directory for the database file
RUN mkdir -p /config

# Run the command to start the Flask application
CMD ["python", "ModLogBot.py"]
