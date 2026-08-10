# DigitalOcean deployment

This project is best deployed to a **DigitalOcean Droplet** running Ubuntu and
Docker Compose. `docker-compose.yml` is for local development; use
`docker-compose.prod.yml` on the Droplet. It does not publish MySQL, and it
binds the API and web containers to loopback so Nginx is the only public entry
point.

## 1. Prepare the Droplet

Create an Ubuntu LTS Droplet, point your domain's DNS `A` record to its IPv4
address, then allow only SSH, HTTP, and HTTPS in both the DigitalOcean Cloud
Firewall and UFW.

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y ca-certificates curl git nginx certbot python3-certbot-nginx
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
exit
```

Sign in again, clone the repository, and create the production environment
file:

```bash
git clone <your-repository-url> paper-crypto-coach
cd paper-crypto-coach
cp .env.example .env
chmod 600 .env
```

## 2. Configure `.env`

Set real, unique values. Do not put this file in Git or in a `NEXT_PUBLIC_*`
environment variable.

```dotenv
ENVIRONMENT=production
MYSQL_DATABASE=paper_crypto_coach
MYSQL_USER=paper_user
MYSQL_PASSWORD=<long-unique-password>
MYSQL_ROOT_PASSWORD=<another-long-unique-password>
DATABASE_URL=mysql+pymysql://paper_user:<url-encoded-password>@db:3306/paper_crypto_coach

JWT_SECRET=<long-random-secret>
JWT_EXPIRE_MINUTES=1440
CORS_ORIGINS=https://lab.example.com
NEXT_PUBLIC_API_URL=https://lab.example.com/api

PAPER_TRADING_FEE_USD=0
PAPER_TRADING_FEE_PERCENT=0.80
PAPER_STARTING_BALANCE=20000.00

# Free server-side parser for every website user.
GROQ_API_KEY=<Groq-key>
GROQ_MODEL=llama-3.1-8b-instant
```

The production API tries Groq first. If Groq is unavailable, Hypothesis Lab
still creates a version with the deterministic rules engine. `GROQ_API_KEY`
stays on the Droplet/API only; the browser never receives it.

For local development, Ollama remains the preferred provider:

```dotenv
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.2
```

When the API runs in Docker and Ollama runs on the host, use
`http://host.docker.internal:11434` (Docker Desktop) or the reachable hostname
of an Ollama service on the same Docker network instead of `127.0.0.1`.

### Google sign-in (OAuth 2.0 / OpenID Connect)

Google login is optional. When its credentials are absent, the Sign in and
Create account pages continue to show email/password login and hide the Google
button.

1. In [Google Cloud Console](https://console.cloud.google.com/), create or
   select a project, configure the OAuth consent screen, then select
   **APIs & Services → Credentials → Create credentials → OAuth client ID**.
2. Choose **Web application**. Under **Authorized JavaScript origins**, add:
   `http://localhost:3001` for local development and your final HTTPS website
   origin, for example `https://app.example.com`, for production.
3. Under **Authorized redirect URIs**, add:
   `http://localhost:8000/auth/google/callback` for local development and
   `https://app.example.com/api/auth/google/callback` for production.
4. Copy the generated client ID and client secret to the Droplet `.env` (never
   to Git), then rebuild the API and web services:

```dotenv
GOOGLE_CLIENT_ID=<Google OAuth client ID>
GOOGLE_CLIENT_SECRET=<Google OAuth client secret>
GOOGLE_REDIRECT_URI=https://app.example.com/api/auth/google/callback
WEB_APP_URL=https://app.example.com
```

```bash
docker compose -f docker-compose.prod.yml up -d --build api web
```

Google requires HTTPS for production web OAuth redirect URIs. Therefore
`http://64.227.31.216/api/auth/google/callback` is suitable only as a
temporary app configuration value; Google normally rejects non-localhost HTTP
redirect URIs. Set up a domain and TLS first, then use that HTTPS URL in both
Google Cloud Console and `GOOGLE_REDIRECT_URI`.

## 3. Start the production stack

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
curl http://127.0.0.1:8000/health
```

The API runs Alembic migrations, then **ensures the market asset catalog**
(`BTC`, `ETH`, `SOL`, …) before it starts. Schema alone is not enough — charts
call `/prices/BTC/candles` and return `Asset 'BTC' not found` if `assets` is
empty (common after a fresh volume or clone that skipped seed).

You can also seed catalog rows without creating the demo user:

```bash
docker compose -f docker-compose.prod.yml exec api python -m app.db.seed --assets-only
```

Future deployments use:

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

## 4. Reverse proxy and TLS

Create `/etc/nginx/sites-available/paper-crypto-coach` and replace
`lab.example.com`:

```nginx
server {
    listen 80;
    server_name lab.example.com;

    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:3001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable it and obtain a certificate:

```bash
sudo ln -s /etc/nginx/sites-available/paper-crypto-coach /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d lab.example.com
```

After changing `NEXT_PUBLIC_API_URL`, rebuild the web image. After changing
`GROQ_API_KEY` or any API setting, rebuild/restart the API:

```bash
docker compose -f docker-compose.prod.yml up -d --build web api
```
# Deploying to a DigitalOcean Droplet

This guide deploys Paper Crypto Coach with the repository's existing
`docker-compose.yml`.

## 1. Create and prepare the server

Create an Ubuntu Droplet, add your SSH key, then connect as a sudo-enabled
user. Install Docker Engine and the Compose plugin using Docker's Ubuntu
installation instructions, or run:

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
```

Log out and back in after changing the Docker group, then verify:

```bash
docker compose version
```

## 2. Configure the application

```bash
git clone <your-repository-url> paper-crypto-coach
cd paper-crypto-coach
cp .env.example .env
chmod 600 .env
```

Edit `.env`; do not commit it. At minimum, set long, unique values for
`JWT_SECRET`, `MYSQL_PASSWORD`, and `MYSQL_ROOT_PASSWORD`. Keep
`DATABASE_URL` consistent with `MYSQL_DATABASE`, `MYSQL_USER`, and
`MYSQL_PASSWORD` (URL-encode password characters that are special in URLs).

Set these production values, replacing the placeholders:

```dotenv
JWT_SECRET=<long-random-secret>
MYSQL_PASSWORD=<database-user-password>
MYSQL_ROOT_PASSWORD=<database-root-password>
DATABASE_URL=mysql+pymysql://paper_user:<database-user-password>@db:3306/paper_crypto_coach
CORS_ORIGINS=https://your-domain
NEXT_PUBLIC_API_URL=https://your-domain
ENVIRONMENT=production
GROQ_API_KEY=<groq-api-key>
PAPER_TRADING_FEE_USD=0
PAPER_TRADING_FEE_PERCENT=0.80
```

Also review `MYSQL_DATABASE`, `MYSQL_USER`, `PAPER_STARTING_BALANCE`, and the
other paper-fee settings in `.env.example` for the values you intend to use.

## 3. Start and migrate

```bash
docker compose up -d --build
docker compose exec api alembic upgrade head
docker compose ps
```

## 4. Network and HTTPS

Allow SSH and web traffic in the DigitalOcean cloud firewall (and UFW if you
enable it): ports `22`, `80`, and `443`. The current Compose file publishes
the web service on `3001` and API on `8000`; keep those ports closed publicly
and place Nginx in front of them. Configure Nginx to serve your domain and
proxy the website to `http://127.0.0.1:3001` and API requests to
`http://127.0.0.1:8000`, then obtain a TLS certificate (for example, with
Certbot). Use the final `https://your-domain` in both `CORS_ORIGINS` and
`NEXT_PUBLIC_API_URL`.

## Hypothesis Lab LLM

In production, Hypothesis Lab uses Groq when `ENVIRONMENT=production` and
`GROQ_API_KEY` is set. Ollama is intended for local/development use; it is not
required on the Droplet. The Lab still has a built-in rules fallback when no
LLM is available.
