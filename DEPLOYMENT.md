# Deployment Guide - Invoice Report Service

## Overview

This guide covers deploying the Invoice Report Service to a production server using Docker and managing the deployment lifecycle.

## Pre-Deployment Checklist

- [ ] GitHub repository created and code pushed
- [ ] Docker account created (for container registry)
- [ ] Server provisioned (Linux VPS, cloud instance, or on-premises)
- [ ] Server has Docker and Docker Compose installed
- [ ] PostgreSQL database accessible from server
- [ ] Authorize.net API credentials verified
- [ ] Domain name configured (optional, for production)
- [ ] SSL certificates obtained (optional, for production)

## Server Requirements

### Minimum Specifications

```
CPU: 2 cores
RAM: 2 GB
Storage: 20 GB (for logs, cache, and Docker images)
OS: Ubuntu 20.04+ or CentOS 8+
Network: Public internet access (for Authorize.net API calls)
```

### Software Requirements

```
Docker: >= 20.10
Docker Compose: >= 1.29
Python: 3.9+ (if running outside Docker)
Git: For cloning repository
```

### Install Docker on Linux

```bash
# Ubuntu/Debian
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add current user to docker group (restart shell after this)
sudo usermod -aG docker $USER

# Verify installation
docker --version
```

## Deployment Steps

### Step 1: Clone Repository on Server

```bash
cd /opt
git clone https://github.com/shankarpuppala-git/invoice_report.git
cd invoice_report
```

### Step 2: Create Environment File

Create `.env` file with production values:

```bash
cat > .env << 'EOF'
ENV=production
DB_HOST=your-postgres-server.com
DB_PORT=5432
DB_NAME=invoice_database
DB_USER=invoice_user
DB_PASSWORD=your_secure_database_password
DB_MIN_CONNECTIONS=5
DB_MAX_CONNECTIONS=20
AUTHORIZE_MERCHANT_ID=your_merchant_id_from_authorize_net
AUTHORIZE_TRANSACTION_KEY=your_transaction_key_from_authorize_net
AUTHORIZE_TIMEOUT=5
AUTHORIZE_MAX_WORKERS=10
AUTH_SERVICE_ENDPOINT=https://auth-service.your-domain.com
AUTH_DB_HOST=auth-postgres-server.com
AUTH_DB_PORT=5432
AUTH_DB_NAME=auth_database
AUTH_DB_USER=auth_user
AUTH_DB_PASSWORD=your_secure_auth_password
EOF
```

**Important:** Protect `.env` file:
```bash
chmod 600 .env
```

### Step 3: Build Docker Image

```bash
# Build image with tag
docker build -t invoice-report:1.0 .

# Verify image built successfully
docker images | grep invoice-report
```

### Step 4: Test Docker Container Locally

```bash
# Run container with port mapping
docker run -d \
  --name invoice-report-test \
  -p 8000:8000 \
  --env-file .env \
  invoice-report:1.0

# Check logs
docker logs invoice-report-test

# Test health endpoint
curl http://localhost:8000/api/v1/invoice/reports/health

# Stop test container
docker stop invoice-report-test
docker rm invoice-report-test
```

### Step 5: Run Production Container

```bash
# Run with restart policy and log limits
docker run -d \
  --name invoice-report \
  --restart unless-stopped \
  -p 8000:8000 \
  --env-file .env \
  --log-driver json-file \
  --log-opt max-size=10m \
  --log-opt max-file=10 \
  -v /opt/invoice_report/logs:/app/logs \
  invoice-report:1.0

# Verify container is running
docker ps | grep invoice-report

# Check logs
docker logs -f invoice-report
```

### Step 6: Configure Reverse Proxy (Nginx)

Create Nginx configuration:

```bash
sudo nano /etc/nginx/sites-available/invoice-report
```

Add configuration:

```nginx
upstream invoice_report {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name invoice-report.your-domain.com;

    # Redirect HTTP to HTTPS (optional)
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name invoice-report.your-domain.com;

    # SSL certificates (use Let's Encrypt with Certbot)
    ssl_certificate /etc/letsencrypt/live/invoice-report.your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/invoice-report.your-domain.com/privkey.pem;

    # SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;

    # Logging
    access_log /var/log/nginx/invoice-report.access.log;
    error_log /var/log/nginx/invoice-report.error.log;

    # Proxy settings
    location / {
        proxy_pass http://invoice_report;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Timeouts for long-running report generation
        proxy_connect_timeout 10s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;
    }

    # Static files (if any)
    location /static/ {
        alias /opt/invoice_report/static/;
        expires 30d;
    }
}
```

Enable Nginx site:

```bash
sudo ln -s /etc/nginx/sites-available/invoice-report \
  /etc/nginx/sites-enabled/invoice-report

# Test Nginx config
sudo nginx -t

# Restart Nginx
sudo systemctl restart nginx
```

### Step 7: Set Up SSL with Let's Encrypt (Optional but Recommended)

```bash
# Install Certbot
sudo apt-get install certbot python3-certbot-nginx

# Generate SSL certificate
sudo certbot certonly --nginx -d invoice-report.your-domain.com

# Auto-renew certificates
sudo systemctl enable certbot.timer
sudo systemctl start certbot.timer
```

### Step 8: Verify Deployment

```bash
# Test API endpoint
curl -X POST https://invoice-report.your-domain.com/api/v1/invoice/reports/generate \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "2024-01-01",
    "end_date": "2024-01-31",
    "application": "btp-NA"
  }' \
  --output test-report.xlsx

# Health check
curl https://invoice-report.your-domain.com/api/v1/invoice/reports/health
```

## Container Management

### View Logs

```bash
# Real-time logs
docker logs -f invoice-report

# Last 100 lines
docker logs --tail 100 invoice-report

# Logs since specific time
docker logs --since 2024-01-27T10:00:00 invoice-report
```

### Restart Container

```bash
# Graceful restart (allows cleanup)
docker restart invoice-report

# Force restart
docker restart -t 10 invoice-report
```

### Stop Container

```bash
docker stop invoice-report

# Remove container
docker rm invoice-report
```

### Update to New Version

```bash
# Build new image
docker build -t invoice-report:1.1 .

# Stop old container
docker stop invoice-report
docker rm invoice-report

# Run new container
docker run -d \
  --name invoice-report \
  --restart unless-stopped \
  -p 8000:8000 \
  --env-file .env \
  --log-driver json-file \
  --log-opt max-size=10m \
  --log-opt max-file=10 \
  invoice-report:1.1

# Verify
docker logs invoice-report
```

## Monitoring & Health Checks

### Systemd Service File (Optional)

Create `/etc/systemd/system/invoice-report.service`:

```ini
[Unit]
Description=Invoice Report Service
After=docker.service
Requires=docker.service

[Service]
Type=simple
Restart=unless-stopped
RestartSec=10

# Start command
ExecStart=/usr/bin/docker start -a invoice-report

# Stop command
ExecStop=/usr/bin/docker stop invoice-report

# Logs
StandardOutput=journal
StandardError=journal
SyslogIdentifier=invoice-report

[Install]
WantedBy=multi-user.target
```

Enable service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable invoice-report
sudo systemctl start invoice-report
```

### Monitoring with Docker Stats

```bash
# View resource usage
docker stats invoice-report

# Monitor in watch mode
docker stats --no-stream
```

### Health Check Endpoint

```bash
# Continuous health check script
#!/bin/bash
while true; do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    http://localhost:8000/api/v1/invoice/reports/health)
  if [ "$STATUS" != "200" ]; then
    echo "Service unhealthy: HTTP $STATUS"
    # Alert or restart
    docker restart invoice-report
  fi
  sleep 60
done
```

## Backup & Recovery

### Backup Database

```bash
# Backup PostgreSQL (run on DB server)
pg_dump -h DB_HOST -U DB_USER -d DB_NAME > backup.sql

# Compress backup
gzip backup.sql

# Store backup securely
mv backup.sql.gz /secure/backup/location/
```

### Backup Application Data

```bash
# Backup logs and configuration
tar -czf invoice-report-backup-$(date +%Y%m%d).tar.gz \
  -C /opt invoice_report/logs \
  -C /opt invoice_report/.env

# Upload to remote storage
aws s3 cp invoice-report-backup-*.tar.gz s3://your-backup-bucket/
```

### Recovery Procedure

```bash
# If container is corrupted:
docker stop invoice-report
docker rm invoice-report

# Rebuild from source
docker build -t invoice-report:latest .

# Run container
docker run -d --name invoice-report ... invoice-report:latest

# If database is corrupted:
# 1. Restore from backup: psql -U user db_name < backup.sql
# 2. Restart services
# 3. Verify data integrity
```

## Scaling for High Load

### Load Balancing (Multiple Containers)

Using Docker Compose:

```yaml
version: '3.8'
services:
  invoice-report-1:
    image: invoice-report:latest
    ports:
      - "8001:8000"
    env_file: .env

  invoice-report-2:
    image: invoice-report:latest
    ports:
      - "8002:8000"
    env_file: .env

  nginx:
    image: nginx:latest
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    depends_on:
      - invoice-report-1
      - invoice-report-2
```

### Database Connection Pooling Tuning

Increase in `.env`:
```
DB_MAX_CONNECTIONS=50
AUTHORIZE_MAX_WORKERS=20
```

### Kubernetes Deployment (Advanced)

For larger deployments, consider Kubernetes with:
- HPA (Horizontal Pod Autoscaling)
- Service mesh (Istio) for traffic management
- Persistent volumes for logs
- ConfigMaps for configuration

## Troubleshooting Deployment

### Container won't start

```bash
# Check logs for errors
docker logs invoice-report

# Common causes:
# 1. Port already in use
netstat -tlnp | grep 8000

# 2. Incorrect .env variables
cat .env | grep -i db

# 3. Out of disk space
df -h
```

### Slow API responses

```bash
# Check database connection status
docker exec invoice-report psql -h $DB_HOST -d $DB_NAME -c "SELECT count(*) FROM pg_stat_activity;"

# Check container resource usage
docker stats invoice-report

# Check Authorize.net API latency in logs
docker logs invoice-report | grep "authorize"
```

### Database connection errors

```bash
# Test database connectivity from container
docker exec invoice-report python -c "
import psycopg2
conn = psycopg2.connect('host=$DB_HOST user=$DB_USER password=$DB_PASSWORD dbname=$DB_NAME')
print('Connected successfully')
"

# Check database logs
# On DB server: tail -f /var/log/postgresql/postgresql.log
```

## Production Best Practices

1. **Security:**
   - Keep `.env` file with restricted permissions (400)
   - Use strong database passwords (16+ characters, mixed case)
   - Enable HTTPS with valid SSL certificates
   - Rotate Authorize.net API keys annually

2. **Reliability:**
   - Set up automated backups (daily minimum)
   - Monitor application health (health check every 60 seconds)
   - Implement graceful shutdown handling
   - Use restart policies (`unless-stopped`)

3. **Performance:**
   - Monitor resource usage (CPU, memory, disk)
   - Keep logs rotated (10m max size, 10 files max)
   - Optimize database queries
   - Monitor API response times

4. **Maintainability:**
   - Keep Docker images updated
   - Document configuration changes
   - Maintain change log
   - Test updates in staging first

---

**Version:** 1.0.0  
**Last Updated:** March 2026
