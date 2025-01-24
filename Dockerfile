# Use an official Python image
FROM python:3.13-slim

# Set the working directory
WORKDIR /usr/src/app

# Copy the requirements file
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app code
COPY ./app ./app
COPY ./alembic ./alembic
COPY alembic.ini alembic.ini

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Expose port 8000 for FastAPI
EXPOSE 8000

# Run the FastAPI app with Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
