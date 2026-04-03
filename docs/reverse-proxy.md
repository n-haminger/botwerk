# Reverse Proxy Configuration

This document provides example configurations for common reverse proxies
to front the Botwerk WebUI. All examples assume the WebUI is running on
`localhost:8080` (the default).

> **Important:** When running behind a reverse proxy, set `behind_proxy: true`
> in your `config.json` so the WebUI trusts `X-Forwarded-*` headers.

---

## nginx

```nginx
upstream botwerk {
    server 127.0.0.1:8080;
    keepalive 32;
}

server {
    listen 443 ssl http2;
    server_name botwerk.example.com;

    # --- TLS termination ---
    ssl_certificate     /etc/letsencrypt/live/botwerk.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/botwerk.example.com/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # --- Security headers ---
    add_header X-Content-Type-Options    "nosniff"              always;
    add_header X-Frame-Options           "SAMEORIGIN"           always;
    add_header X-XSS-Protection          "1; mode=block"        always;
    add_header Referrer-Policy            "strict-origin-when-cross-origin" always;
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
    add_header Content-Security-Policy   "default-src 'self'; connect-src 'self' wss:; style-src 'self' 'unsafe-inline'; script-src 'self'" always;

    # --- Proxy settings ---
    location / {
        proxy_pass         http://botwerk;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;

        # WebSocket upgrade
        proxy_set_header   Upgrade    $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }

    # Optional: increase body size for file uploads
    client_max_body_size 100M;
}

# Redirect HTTP -> HTTPS
server {
    listen 80;
    server_name botwerk.example.com;
    return 301 https://$host$request_uri;
}
```

---

## Caddy

Caddy handles TLS certificates automatically via Let's Encrypt.

```caddyfile
botwerk.example.com {
    reverse_proxy localhost:8080

    header {
        X-Content-Type-Options    "nosniff"
        X-Frame-Options           "SAMEORIGIN"
        X-XSS-Protection          "1; mode=block"
        Referrer-Policy            "strict-origin-when-cross-origin"
        Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"
        Content-Security-Policy   "default-src 'self'; connect-src 'self' wss:; style-src 'self' 'unsafe-inline'; script-src 'self'"
    }
}
```

Caddy automatically handles WebSocket upgrades and TLS provisioning.
No additional configuration is needed for either.

---

## Traefik

### Docker labels (Docker Compose)

```yaml
services:
  botwerk:
    image: botwerk:latest
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.botwerk.rule=Host(`botwerk.example.com`)"
      - "traefik.http.routers.botwerk.entrypoints=websecure"
      - "traefik.http.routers.botwerk.tls.certresolver=letsencrypt"
      - "traefik.http.services.botwerk.loadbalancer.server.port=8080"
      # Security headers middleware
      - "traefik.http.middlewares.botwerk-headers.headers.customResponseHeaders.X-Content-Type-Options=nosniff"
      - "traefik.http.middlewares.botwerk-headers.headers.customResponseHeaders.X-Frame-Options=SAMEORIGIN"
      - "traefik.http.middlewares.botwerk-headers.headers.customResponseHeaders.X-XSS-Protection=1; mode=block"
      - "traefik.http.middlewares.botwerk-headers.headers.customResponseHeaders.Referrer-Policy=strict-origin-when-cross-origin"
      - "traefik.http.middlewares.botwerk-headers.headers.stsSeconds=63072000"
      - "traefik.http.middlewares.botwerk-headers.headers.stsIncludeSubdomains=true"
      - "traefik.http.middlewares.botwerk-headers.headers.stsPreload=true"
      - "traefik.http.routers.botwerk.middlewares=botwerk-headers"
    ports:
      - "8080:8080"

  traefik:
    image: traefik:v3
    command:
      - "--providers.docker=true"
      - "--entrypoints.websecure.address=:443"
      - "--certificatesresolvers.letsencrypt.acme.tlschallenge=true"
      - "--certificatesresolvers.letsencrypt.acme.email=admin@example.com"
      - "--certificatesresolvers.letsencrypt.acme.storage=/letsencrypt/acme.json"
    ports:
      - "443:443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - letsencrypt:/letsencrypt

volumes:
  letsencrypt:
```

### File provider (non-Docker)

Create a dynamic config file (e.g. `/etc/traefik/dynamic/botwerk.yml`):

```yaml
http:
  routers:
    botwerk:
      rule: "Host(`botwerk.example.com`)"
      entryPoints:
        - websecure
      service: botwerk
      tls:
        certResolver: letsencrypt
      middlewares:
        - botwerk-headers

  services:
    botwerk:
      loadBalancer:
        servers:
          - url: "http://127.0.0.1:8080"

  middlewares:
    botwerk-headers:
      headers:
        customResponseHeaders:
          X-Content-Type-Options: "nosniff"
          X-Frame-Options: "SAMEORIGIN"
          X-XSS-Protection: "1; mode=block"
          Referrer-Policy: "strict-origin-when-cross-origin"
        stsSeconds: 63072000
        stsIncludeSubdomains: true
        stsPreload: true
```

And reference it in your static config (`/etc/traefik/traefik.yml`):

```yaml
entryPoints:
  websecure:
    address: ":443"

providers:
  file:
    directory: /etc/traefik/dynamic
    watch: true

certificatesResolvers:
  letsencrypt:
    acme:
      email: admin@example.com
      storage: /etc/traefik/acme.json
      tlsChallenge: {}
```

Traefik handles WebSocket upgrades automatically when the backend
responds with the appropriate `101 Switching Protocols`.
