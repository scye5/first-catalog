# FIRST Catalog API

A Docker Compose project for searching an astronomical catalog by source name or sky position. It uses PostgreSQL 16, pgSphere spatial indexes, and a Python FastAPI service.

See [instuction.md](instuction.md) for the complete installation, CSV import, indexing, proxy, troubleshooting, and migration guide.

## Basic setup

Requirements: Git, Docker Engine with Docker Compose, and your own `FIRST.csv` or a database backup. On Windows, use WSL 2 or Docker Desktop with WSL integration.

```bash
git clone https://github.com/scye5/first-catalog.git
cd first-catalog
cp .env.example .env
```

Edit `.env` and replace the placeholder with your database password:

```dotenv
POSTGRES_PASSWORD='your_database_password'
```

Build the images and start PostgreSQL:

```bash
sudo docker compose build
sudo docker compose up -d --wait db
```

**Prepare the database before starting searches:**

- For a fresh catalog, place the file at `data/FIRST.csv`, then follow [CSV import and index setup](instuction.md#initialize-a-new-database-from-csv). Importing alone does not create the pgSphere position column and indexes.
- To migrate an existing catalog, follow [backup and restore](instuction.md#back-up-and-move-to-another-machine) instead.
- If this project already has a populated and indexed database volume, skip initialization.

The CSV and database backups are excluded from Git. Import and index creation are one-time operations; do not repeat them on an initialized database.

Start the API:

```bash
sudo docker compose up -d api
```

Open **[http://localhost:8000/docs](http://localhost:8000/docs)** for interactive API documentation. No local Python installation or manual database environment exports are needed for the container workflow.

## Configuration

| Setting | Default / location |
| --- | --- |
| Database password | `POSTGRES_PASSWORD` in `.env` |
| Database name / user | `astronomy` / `postgres` in `compose.yaml` |
| API address | `http://127.0.0.1:8000` |
| PostgreSQL host address | `127.0.0.1:5432` |
| API-to-database address | `db:5432` on the Compose network |
| Database storage | Persistent `pgdata` Docker volume |

Keep `.env` private. For an existing database, use its current password: editing `.env` does not change the password stored by PostgreSQL. After changing container configuration, apply it with `sudo docker compose up -d`.

Both published ports are local-only. This configuration is intended for local use; see the detailed guide before exposing it to other users.

If your network requires a proxy, follow [proxy configuration](instuction.md#configure-proxies). Once the shell and daemon proxies are configured, preserve the shell settings for builds:

```bash
sudo --preserve-env=HTTP_PROXY,HTTPS_PROXY,NO_PROXY docker compose build
```

## Call the API

Case-insensitive exact name search:

```bash
curl --get http://127.0.0.1:8000/sources \
  --data-urlencode 'name=J030004.5+000946' \
  --data-urlencode 'limit=10'
```

Cone search:

```bash
curl --get http://127.0.0.1:8000/sources/cone \
  --data-urlencode 'ra=45.01904166666666' \
  --data-urlencode 'dec=0.16301388888888887' \
  --data-urlencode 'radius=0.01' \
  --data-urlencode 'limit=50'
```

RA, Dec, radius, and returned separations use **decimal degrees**. RA must be in `[0, 360)`, Dec in `[-90, 90]`, and radius in `(0, 180]`. `limit` defaults to 100 and accepts 1–1000. Cone results are ordered by angular separation.

Responses include `count`, `limit`, and `results`; `count` reflects the returned rows, not all possible matches. Encode a literal `+` in a name as `%2B` when writing URLs manually. The `/` and `/favicon.ico` routes are not implemented; their 404 responses are expected.

## Daily usage

Run these commands from the project directory:

```bash
# Start services using the existing database.
sudo docker compose up -d

# Check status and follow API logs.
sudo docker compose ps
sudo docker compose logs -f api

# Rebuild and update the API after editing Python code.
sudo docker compose up -d --build api

# Run a query directly inside the API container.
sudo docker compose exec api python queries.py name 'J030004.5+000946'

# Stop services while retaining data.
sudo docker compose stop
```

Ctrl+C exits log viewing without stopping the API. Use the proxy-preserving command prefix for rebuilds if needed.

Database data survives container recreation. **`docker compose down -v` deletes the database volume.** Keep the same Compose project name/directory when reusing an existing volume, and make backups before migration or database changes.

For errors, consult [troubleshooting](instuction.md#troubleshooting).
