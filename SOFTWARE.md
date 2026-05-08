# Code layout virtual environment

kassafu/
├── kassafu.py          # Main application, options for usage.
├── test_kassafu.py     # Test script including remote server (priority)
├── requirements.txt    # Dependencies to install like sumup.
├── .env.example        # Environment variables template.
├── example.cpp         # How to use the code from C++.
├── setup.sh            # Install all dependencies.
├── service             # Tools to make a startup service.
  ├── kassafu.service   # Linux service details.
  ├── install.sh        # Install the service.
  ├── kassafu.sh        # Runner for the service.
├── run.sh              # Start the service.
├── README.md           # Documentation
├── SOFTWARE.md         # Explain the software
└── kassafu.log         # Generated log file

# Code layout Docker

## Startup script
```
dockerfile

# Use an official Python runtime as base image
FROM python:3.9-slim

# Set environment variables to prevent Python from buffering logs and writing pycache
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Set work directory inside the container
WORKDIR /app

# Install system dependencies if needed (for sumup or other native libs)
# RUN apt-get update && apt-get install -y gcc libffi-dev && rm -rf /var/lib/apt/lists/*

# Copy only requirements first to leverage Docker caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Create a volume for the log file if you want persistence
# VOLUME ["/app/logs"]

# Expose the port your app runs on (if applicable, adjust as needed)
# EXPOSE 8000

# Command to run the application
CMD ["python", "kassafu.py"]
```

# Software Flow
<img width="3133" height="2186" alt="image" src="https://github.com/user-attachments/assets/0f1c9ee0-111d-4b9b-95f1-2113679a3966" />

# Service
- Copy kassafu.py to  /etc/systemd/system/
- Copy kassafu.sh to  /etc/systemd/system/
- Copy kassafu.service to /etc/systemd/system/
- ldconfig
- systemctl start kassafu
- systemctl enable kassafu
- systemctl daemon-reload
- service kassafu status  # Should show it's running perfect.
- Check port 8888 is open and listening to payment requests. Run test_kassafu.py.

# Dependencies

What to install for this project:

fastapi==0.104.1
uvicorn==0.24.0
requests==2.31.0
python-dotenv==1.0.0
httpx==0.25.1
