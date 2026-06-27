# OpenTalking Homepage Deployment

This directory contains the OpenTalking product homepage. The app is built as static files with Vite, then served by a lightweight FastAPI + uvicorn server.

## Requirements

- Node.js 18+
- Python 3.9+
- A public server port, for example `<PORT>`
- A project directory, for example `<PROJECT_DIR>`

> Replace placeholders such as `<PROJECT_DIR>`, `<PORT>`, and `<SERVICE_NAME>` with your own values. This guide does not assume a fixed server path.

## 1. Clone Or Update

Clone the repository:

```bash
cd <PARENT_DIR>
git clone https://github.com/datascale-ai/opentalking.git <PROJECT_DIR>
```

If the repository already exists:

```bash
cd <PROJECT_DIR>
git pull
```

## 2. Build Static Files

```bash
cd <PROJECT_DIR>/apps/homepage
npm install
npm run build
```

After a successful build, Vite generates:

```text
<PROJECT_DIR>/apps/homepage/dist
```

The production server reads files from this `dist` directory.

## 3. Install Python Runtime

Create a virtual environment anywhere you prefer. A common choice is inside the repository root:

```bash
cd <PROJECT_DIR>
uv venv
source .venv/bin/activate
uv pip install fastapi uvicorn
```

## 4. Start With uvicorn

```bash
cd <PROJECT_DIR>/apps/homepage

# 注意，这一步要放tmux或者后台进程
<PROJECT_DIR>/.venv/bin/uvicorn homepage_server:app --host 0.0.0.0 --port <PORT>
```

Use `--host 0.0.0.0` for public access.

Then open:

```text
http://<SERVER_IP>:<PORT>/
```

Health check:

```bash
curl http://127.0.0.1:<PORT>/health
```

GitHub stats proxy check:

```bash
curl http://127.0.0.1:<PORT>/github-api/repos/datascale-ai/opentalking
```

The GitHub stats endpoint should return JSON containing `stargazers_count` and `forks_count`.

Traffic dashboard:

```text
http://127.0.0.1:<PORT>/traffic
http://127.0.0.1:<PORT>/en/traffic
```

The dashboard is linked from the OpenTalking logo in the footer. The server stores analytics events in SQLite at:

```text
<PROJECT_DIR>/apps/homepage/.analytics/homepage_analytics.sqlite3
```

You can override the path if needed:

```bash
HOMEPAGE_ANALYTICS_DB="<CUSTOM_SQLITE_PATH>"
```

## 5. Run As A systemd Service

Create a service file:

```bash
sudo nano /etc/systemd/system/<SERVICE_NAME>.service
```

Example:

```ini
[Unit]
Description=OpenTalking Homepage
After=network.target

[Service]
Type=simple
WorkingDirectory=<PROJECT_DIR>/apps/homepage
ExecStart=<PROJECT_DIR>/.venv/bin/uvicorn homepage_server:app --host 0.0.0.0 --port <PORT>
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable <SERVICE_NAME>
sudo systemctl start <SERVICE_NAME>
```

Check status:

```bash
sudo systemctl status <SERVICE_NAME>
```

View logs:

```bash
journalctl -u <SERVICE_NAME> -f
```

## 6. Update Deployment

```bash
cd <PROJECT_DIR>
git pull

cd <PROJECT_DIR>/apps/homepage
npm install
npm run build

sudo systemctl restart <SERVICE_NAME>
```

## 7. Domain Binding

Point your domain DNS `A` record to the server public IP.

For a quick test, you can visit:

```text
http://<DOMAIN>:<PORT>/
```

For production, it is recommended to put Nginx or Caddy in front of uvicorn and proxy port `80` / `443` to `127.0.0.1:<PORT>`. In that case, uvicorn can be started with:

```bash
<PROJECT_DIR>/.venv/bin/uvicorn homepage_server:app --host 127.0.0.1 --port <PORT>
```

When using a reverse proxy, only Nginx or Caddy needs to expose public ports. uvicorn can stay on localhost.
