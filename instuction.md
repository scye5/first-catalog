# FIRST Catalog: PostgreSQL, pgSphere, and REST API

Run a FIRST astronomical catalog database and a Python REST API with Docker Compose. PostgreSQL stores the CSV data; pgSphere supports indexed spherical cone searches; FastAPI exposes name and position searches.

Commands below assume the project is in `~/first-catalog`; substitute your own project directory when deploying elsewhere. Run Linux commands in WSL Ubuntu unless a block is explicitly labeled PowerShell. This README does not perform any installation itself.

## Contents

- [Architecture and files](#architecture-and-files)
- [Install WSL and Docker](#install-wsl-and-docker)
- [Configure proxies](#configure-proxies)
- [Configure and build the project](#configure-and-build-the-project)
- [Initialize a new database from CSV](#initialize-a-new-database-from-csv)
- [Call the API](#call-the-api)
- [Query using Python or SQL](#query-using-python-or-sql)
- [Daily operation](#daily-operation)
- [Back up and move to another machine](#back-up-and-move-to-another-machine)
- [Troubleshooting](#troubleshooting)
- [Deployment notes and references](#deployment-notes-and-references)

## Architecture and files

```text
Browser / curl / Python HTTP client
                |
       localhost:8000
                |
     api container (FastAPI)
                |
          db:5432
                |
   db container (PostgreSQL 16 + pgSphere)
                |
      persistent pgdata volume
```

| File or directory | Purpose |
| --- | --- |
| `Dockerfile` | PostgreSQL 16 Bookworm image with the pgSphere package |
| `Dockerfile.api` | Python 3.14 image running Uvicorn |
| `compose.yaml` | Services, network, ports, credentials, health check, and volume |
| `.env` | Local database password used by Compose |
| `.dockerignore` | Excludes credentials, CSV files, backups, and local Python files from build context |
| `requirements.txt` | Pinned Python dependencies |
| `import_csv.py` | Transactional CSV import into `first_raw` and `sources` |
| `queries.py` | Parameterized SQL queries and Python command-line interface |
| `api.py` | FastAPI endpoints |
| `data/FIRST.csv` | Input catalog; supplied separately |
| `backups/` | Database dumps; created as needed |

The database and API are published on the host's loopback interface only. The API connects to PostgreSQL using the Compose service name `db`. A Python process running directly in WSL instead uses `127.0.0.1`.

**Starting the containers does not import the CSV or create the spatial indexes.** For a fresh installation, complete the database initialization section before using the search endpoints. For an existing installation, keep its volume and skip initialization. For migration, restore a backup instead of importing again.

## Install WSL and Docker

### 1. Install WSL 2

On Windows, open an administrator PowerShell terminal:

```powershell
wsl --install -d Ubuntu-24.04
```

Restart if requested, launch Ubuntu, and create your Linux user. Verify:

```powershell
wsl --update
wsl --list --verbose
```

The distribution should report version `2`. If needed:

```powershell
wsl --set-version Ubuntu-24.04 2
```

An existing supported Ubuntu distribution can also be used. Always use the repository codename of the installed system rather than copying a codename from another Ubuntu release.

Check inside Ubuntu:

```bash
cat /etc/os-release
dpkg --print-architecture
```

`amd64` is appropriate for Intel/AMD 64-bit computers; `arm64` is appropriate for ARM64 computers. APT selects the architecture automatically.

### 2. Enable systemd if necessary

Check PID 1:

```bash
ps -p 1 -o comm=
```

If it is not `systemd`, edit `/etc/wsl.conf`, preserving other settings:

```bash
sudo nano /etc/wsl.conf
```

Ensure it contains:

```ini
[boot]
systemd=true
```

Then run `wsl --shutdown` from PowerShell and reopen Ubuntu. This shuts down all running WSL distributions.

### 3. Install Docker Engine from Docker's repository

This guide uses Docker Engine inside WSL, managed by systemd. Docker Desktop is an alternative; if using Desktop, enable its WSL integration and configure its proxy through Desktop settings rather than installing a second daemon using these steps.

If switching from Ubuntu's Docker packages, first check for conflicting packages:

```bash
dpkg -l docker.io docker-compose-v2 docker-compose docker-buildx containerd runc
```

Remove installed conflicting packages before installing Docker CE. On a machine with existing workloads, stop them deliberately before changing engines. Leaving `docker-compose-v2` installed can cause a file conflict with Docker CE’s Compose plugin.

```bash
sudo apt remove docker.io docker-compose-v2 docker-compose docker-buildx containerd runc
```

If APT reports that a package cannot be located, omit that package name. On a fresh machine with none installed, skip removal.

Configure the official repository:

```bash
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL --connect-timeout 10 --max-time 60 \
  https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

If the key download fails, resolve connectivity using the proxy section before continuing.

```bash
sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
apt-cache policy docker-ce
```

Continue only when `Candidate:` lists a version and the Docker repository updated successfully:

```bash
sudo apt install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker version
sudo docker compose version
sudo docker run --rm hello-world
```

`docker version` should report a Client and Server. `hello-world` should print `Hello from Docker!`. A failed image download can be a network problem even when Docker itself is installed correctly.

## Configure proxies

Skip this section on a machine with working direct internet access. Proxy addresses are machine-specific configuration; do not bake them into the application images.

The commands below use `http://127.0.0.1:7897` as an example proxy address. Replace the address and port with your own proxy settings, and confirm WSL can reach it. Other WSL networking configurations may require the Windows host's reachable IP and a proxy configured to accept those connections.

### Terminal and build-client proxy

Add this block once to `~/.bashrc`:

```bash
export HTTP_PROXY=http://127.0.0.1:7897
export HTTPS_PROXY=http://127.0.0.1:7897
export NO_PROXY=localhost,127.0.0.1,::1
export http_proxy="$HTTP_PROXY"
export https_proxy="$HTTPS_PROXY"
export no_proxy="$NO_PROXY"
```

Load it in the current terminal:

```bash
source ~/.bashrc
```

An HTTP proxy URL can tunnel HTTPS requests, so `HTTPS_PROXY=http://...` is intentional. Keep the proxy application running when downloading packages or images. New interactive Bash sessions will load these variables automatically.

`sudo` can remove proxy variables. For builds use:

```bash
sudo --preserve-env=HTTP_PROXY,HTTPS_PROXY,NO_PROXY \
  docker compose build
```

For a specific command, explicit variables are also possible:

```bash
sudo env HTTPS_PROXY=http://127.0.0.1:7897 \
  curl -fsSL --connect-timeout 10 --max-time 60 \
  https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
```

### Docker daemon proxy

The background Docker service needs its own settings:

```bash
sudo mkdir -p /etc/systemd/system/docker.service.d
sudo tee /etc/systemd/system/docker.service.d/http-proxy.conf > /dev/null <<'EOF'
[Service]
Environment="HTTP_PROXY=http://127.0.0.1:7897"
Environment="HTTPS_PROXY=http://127.0.0.1:7897"
Environment="NO_PROXY=localhost,127.0.0.1,::1"
EOF

sudo systemctl daemon-reload
sudo systemctl restart docker
sudo systemctl show --property=Environment docker
```

This file persists across WSL restarts. Restarting Docker may interrupt running containers. A `proxy.conf` file merely stored in the project directory is not automatically read by Docker.

Explicit proxy configuration in `/etc/docker/daemon.json` takes precedence over the service environment. Inspect it if the effective proxy does not match expectations; preserve any unrelated settings.

### Proxy access from build steps

Downloading a base image and running `apt-get` or `pip` inside a build container use different network contexts. The daemon proxy alone does not configure `RUN` commands.

If a build reaches `RUN apt-get update` or `RUN pip install` and then fails for network reasons, supply build arguments with a proxy address reachable **from the build container**:

```bash
sudo --preserve-env=HTTP_PROXY,HTTPS_PROXY,NO_PROXY \
  docker compose build \
    --build-arg HTTP_PROXY=http://HOST_REACHABLE_ADDRESS:7897 \
    --build-arg HTTPS_PROXY=http://HOST_REACHABLE_ADDRESS:7897
```

Replace the placeholder. In the normal isolated build network, `127.0.0.1` refers to the build container, not WSL or Windows. The proxy may need to listen on a reachable host interface. Do not add proxy `ENV` lines to the Dockerfiles just to fix downloads.

## Configure and build the project

### Project configuration

Place the application files in `~/first-catalog`, then:

```bash
cd ~/first-catalog
nano .env
```

Set the following using your own password:

```dotenv
POSTGRES_PASSWORD='replace_with_your_database_password'
```

For an existing database, use its current password. Single quotes prevent Compose interpolation of `$` in a password; choose a value without embedded single quotes for this form. Protect the file:

```bash
chmod 600 .env
```

Do not commit `.env` or database dumps. Suggested `.gitignore` entries:

```gitignore
.env
.venv/
__pycache__/
*.pyc
data/
backups/
```

The project uses this `compose.yaml`:

```yaml
services:
  db:
    build:
      context: .
      dockerfile: Dockerfile
    environment:
      POSTGRES_DB: astronomy
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in .env}
    ports:
      - "127.0.0.1:5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d astronomy"]
      interval: 5s
      timeout: 5s
      retries: 20
    restart: unless-stopped

  api:
    build:
      context: .
      dockerfile: Dockerfile.api
    environment:
      PGHOST: db
      PGPORT: "5432"
      PGDATABASE: astronomy
      PGUSER: postgres
      PGPASSWORD: ${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in .env}
    ports:
      - "127.0.0.1:8000:8000"
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped

volumes:
  pgdata:
```

The PostgreSQL image installs pgSphere binaries, but `CREATE EXTENSION` must still be executed in the database. The API image installs `requirements.txt`, copies the three Python scripts into `/app`, and starts:

```text
uvicorn api:app --host 0.0.0.0 --port 8000
```

The API must bind to `0.0.0.0` inside its container so the host port mapping can reach it. The host binding remains local-only.

### Build and start

If a manually started Uvicorn process is using port 8000, stop that process with Ctrl+C first.

Validate the Compose configuration without printing interpolated passwords:

```bash
sudo docker compose config --quiet
```

Build, without a proxy:

```bash
sudo docker compose build
```

Or build with the previously configured shell proxy:

```bash
sudo --preserve-env=HTTP_PROXY,HTTPS_PROXY,NO_PROXY docker compose build
```

Start the database and wait for readiness:

```bash
sudo docker compose up -d --wait db
sudo docker compose ps
```

Choose one path:

- **Fresh database:** import the CSV and create indexes using the next section.
- **Existing working database:** skip initialization and start the API.
- **Database backup:** follow the restore instructions instead of CSV initialization.

After the database is prepared:

```bash
sudo docker compose up -d api
sudo docker compose logs --tail=50 api
```

Open <http://localhost:8000/docs>.

## Initialize a new database from CSV

### 1. Confirm the input and mappings

Place the input at `data/FIRST.csv`. On WSL, a Windows path such as `C:\data\FIRST.csv` is usually available at `/mnt/c/data/FIRST.csv`; copy it into the project's `data` directory if necessary.

The expected FIRST header is:

```text
recno,FIRST,RAJ2000,DEJ2000,p(S),Fpeak,Fint,Rms,Maj,Min,PA,fMaj,fMin,fPA,Field,N1,r1,m1,c1,N2,r2,m2,Ep,Ep(JD),s_Ep(JD)
```

The importer contains:

```python
NAME_COL = "FIRST"
RA_COL = "RAJ2000"
DEC_COL = "DEJ2000"
```

| CSV field | Destination | Interpretation |
| --- | --- | --- |
| `FIRST` | `sources.name` | Source name, e.g. `J030004.5+000946` |
| `RAJ2000` | `sources.ra_deg` | Decimal degrees, `0 <= RA < 360` |
| `DEJ2000` | `sources.dec_deg` | Decimal degrees, `-90 <= Dec <= 90` |
| Every field | `first_raw` and `sources.attributes` | Original values retained |

The sample input uses decimal degrees. Do not multiply these RA values by 15. Other catalogs using RA hours or sexagesimal strings require conversion before this importer can use them. Queries should use the same coordinate frame as the catalog; the API does not transform coordinates or propagate positions between epochs.

Special characters in headers are handled by `psycopg.sql.Identifier`. Empty CSV fields become SQL NULL. All raw columns are text; the JSON attributes also retain text values or nulls. Only the canonical RA and Dec columns are converted to floating-point numbers.

### 2. Import once

Run the importer in a temporary API container, mounting the input read-only:

```bash
sudo docker compose run --rm \
  -v "$PWD/data:/data:ro" \
  api python import_csv.py /data/FIRST.csv
```

Compose supplies the database connection environment. No host Python installation, virtual environment, or manual `PG*` exports are needed. The one-off command does not publish the API service's ports.

The importer creates `first_raw` and `sources` in one transaction and reports `Imported N rows` on success. Invalid rows roll back that transaction. It is intentionally **not idempotent**: running it again after success fails because the tables already exist. Inspect existing tables before deciding whether to reload; do not automatically drop them.

If you edited `import_csv.py` after building, rebuild the API image before this command:

```bash
sudo docker compose build api
```

Use the proxy-preserving variant if your build needs it.

### 3. Enable pgSphere and create indexes

Run the following only after a successful fresh import. The script stops on an error and applies the schema changes transactionally:

```bash
sudo docker compose exec -T db \
  psql -U postgres -d astronomy -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_sphere;

ALTER TABLE sources
ADD COLUMN position spoint
GENERATED ALWAYS AS (
    spoint(radians(ra_deg), radians(dec_deg))
) STORED;

CREATE INDEX sources_position_gist
    ON sources USING gist (position);

CREATE INDEX sources_name_lower_idx
    ON sources (lower(name));

COMMIT;

ANALYZE sources;
SQL
```

This is a one-time schema step; it is not intended to run against an already indexed database. A backup restore includes this schema and does not require the step again.

The GiST index covers the combined spherical position, supporting cone searches across RA wraparound and near the poles. Numeric pgSphere constructors use radians; the application converts degree inputs with `radians()` and reports separations in degrees.

### 4. Verify data and index use

```bash
sudo docker compose exec db psql -U postgres -d astronomy
```

At the SQL prompt:

```sql
SELECT count(*) FROM first_raw;
SELECT count(*) FROM sources;
SELECT extname, extversion FROM pg_extension;
\d sources

EXPLAIN (ANALYZE, BUFFERS)
SELECT id, name
FROM sources
WHERE position <@ scircle(
    spoint(radians(45.01904166666666), radians(0.16301388888888887)),
    radians(0.01)
);
```

For a selective search in a large catalog, look for an index or bitmap index scan referencing `sources_position_gist`. PostgreSQL can legitimately prefer a sequential scan for small tables or broad searches. The query is indexable, but the planner chooses whether to use the index. Do not disable sequential scans globally to force a particular plan.

Exit with `\q`, then start the API if it is not running:

```bash
sudo docker compose up -d api
```

## Call the API

### Interactive documentation

- Swagger UI: <http://localhost:8000/docs>
- Alternative API documentation: <http://localhost:8000/redoc>
- OpenAPI schema: <http://localhost:8000/openapi.json>

The current application defines no `/` homepage and no `/favicon.ico`; 404 responses for those URLs are expected.

### Name search

```bash
curl --fail-with-body --get http://127.0.0.1:8000/sources \
  --data-urlencode 'name=J030004.5+000946' \
  --data-urlencode 'limit=10'
```

This performs a **case-insensitive exact match**, not a substring or fuzzy match. Results are ordered by database ID. The name must contain 1–255 characters.

When typing a URL manually, encode a literal `+` as `%2B`:

```text
http://localhost:8000/sources?name=J030004.5%2B000946
```

Example response for the supplied sample (the generated ID can differ):

```json
{
  "count": 1,
  "limit": 10,
  "results": [
    {
      "id": 1,
      "name": "J030004.5+000946",
      "ra_deg": 45.01904166666666,
      "dec_deg": 0.16301388888888887
    }
  ]
}
```

### Cone search

```bash
curl --fail-with-body --get http://127.0.0.1:8000/sources/cone \
  --data-urlencode 'ra=45.01904166666666' \
  --data-urlencode 'dec=0.16301388888888887' \
  --data-urlencode 'radius=0.01' \
  --data-urlencode 'limit=50'
```

| Parameter | Required | Units and allowed values |
| --- | --- | --- |
| `ra` | Yes | Decimal degrees, `0 <= ra < 360` |
| `dec` | Yes | Decimal degrees, `-90 <= dec <= 90` |
| `radius` | Yes | Angular radius in degrees, `0 < radius <= 180` |
| `limit` | No | Integer 1–1000; default 100 |

All numeric coordinates must be finite. Convert arcminutes to degrees by dividing by 60; convert arcseconds by dividing by 3600. For example, a 30-arcsecond radius is approximately `0.008333333333333333` degrees.

The response contains `center`, `radius_deg`, `count`, `limit`, and `results`. Each cone result includes `id`, `name`, `ra_deg`, `dec_deg`, and `separation_deg`. Results are ordered by angular separation, with ID as the tie-breaker.

For both endpoints, `count` is the number returned after the limit, not the total number of matches. A successful search with no matches returns HTTP 200 and an empty `results` list. There is no pagination or total-count endpoint in the current implementation.

### Call from Python without extra dependencies

```python
import json
from urllib.parse import urlencode
from urllib.request import urlopen

params = urlencode({
    "ra": 45.01904166666666,
    "dec": 0.16301388888888887,
    "radius": 0.01,
    "limit": 50,
})

with urlopen(f"http://127.0.0.1:8000/sources/cone?{params}", timeout=30) as response:
    data = json.load(response)

for source in data["results"]:
    print(source["name"], source["separation_deg"])
```

### HTTP errors

| Status | Interpretation |
| --- | --- |
| 200 | Query succeeded, including zero matches |
| 404 | Requested route does not exist |
| 422 | Missing or invalid query parameters; inspect response `detail` |
| 500 | Application/database error; inspect API logs |

The current API does not translate database failures into custom error responses. Uvicorn startup and `/docs` working do not by themselves prove the database is ready; test a real query.

## Query using Python or SQL

### Inside the container (recommended)

```bash
sudo docker compose exec api \
  python queries.py name 'J030004.5+000946'

sudo docker compose exec api \
  python queries.py cone 45.01904166666666 0.16301388888888887 0.01 --limit 50
```

### Directly in WSL (optional development workflow)

```bash
sudo apt install -y python3-venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Use a Python version compatible with the pinned requirements; the API image uses Python 3.14. Set these variables in the same shell as the Python process:

```bash
export PGHOST=127.0.0.1
export PGPORT=5432
export PGDATABASE=astronomy
export PGUSER=postgres
read -rsp 'PostgreSQL password: ' PGPASSWORD
export PGPASSWORD
echo

python queries.py name 'J030004.5+000946'
```

To run the API manually, first stop the API container so port 8000 is free:

```bash
sudo docker compose stop api
uvicorn api:app --host 127.0.0.1 --port 8000
```

`psycopg.connect("")` reads the `PG*` environment variables. It does not automatically load `.env`. Host exports disappear when the shell exits; the container workflow avoids this requirement.

### Inspect raw fields using SQL

```bash
sudo docker compose exec db psql -U postgres -d astronomy
```

```sql
SELECT "FIRST", "p(S)", "Ep(JD)"
FROM first_raw
LIMIT 5;

SELECT name, attributes ->> 'Fpeak' AS peak_flux_raw
FROM sources
LIMIT 5;
```

Quoted raw identifiers preserve their case and punctuation. Flux units and meanings of ancillary fields should be taken from the catalog documentation; the importer preserves them without interpreting them.

## Daily operation

Run from the project directory:

```bash
# Start/reconcile services; reuse existing images and database volume.
sudo docker compose up -d

# Status and recent logs.
sudo docker compose ps
sudo docker compose logs --tail=100 api db

# Follow API logs; Ctrl+C stops log viewing only.
sudo docker compose logs -f api

# Stop services, retaining containers and data.
sudo docker compose stop

# Start previously stopped containers.
sudo docker compose start
```

After changing Python code or dependencies, rebuild and recreate the API:

```bash
sudo docker compose up -d --build api
```

Use the proxy-preserving prefix when needed. Source files are copied into the image, not mounted live; `restart` alone does not apply source edits. Changes to Compose environment values also require container recreation with `up -d`, not just `restart`.

`docker compose down` removes project containers and the network but normally retains the named database volume. **`docker compose down -v` deletes the database volume and its data.** Do not use it as a routine troubleshooting step.

Compose derives a project name from the directory unless overridden. Moving/renaming the directory or changing `-p`/`COMPOSE_PROJECT_NAME` can select a different volume and make the database appear empty. Preserve the existing project name when reusing existing data.

With `restart: unless-stopped`, containers that were running can restart when Docker restarts. WSL itself must be running; these settings do not launch WSL at Windows login. Containers explicitly stopped remain stopped until started again.

## Back up and move to another machine

### Create a logical backup

```bash
cd ~/first-catalog
mkdir -p backups
sudo docker compose exec -T db \
  pg_dump -U postgres -d astronomy -Fc \
  > backups/astronomy.dump
```

Check that `pg_dump` exits successfully before relying on the file. Each use of this filename overwrites an older dump; choose a different filename to keep multiple versions.

The custom-format dump contains schema, table data, index definitions, and the extension declaration. It does not contain the PostgreSQL/pgSphere binaries, container images, or database role passwords. Keep a tested backup independently of the Docker volume.

### Deploy and restore on a new machine

1. Install Docker and Compose. Configure a proxy only if needed there.
2. Copy the project source, Dockerfiles, Compose file, pinned requirements, and the dump.
3. Create a local `.env`. Its password initializes the new database; it need not equal the source machine's password.
4. Build the images and start an empty PostgreSQL database:

   ```bash
   sudo docker compose build
   sudo docker compose up -d --wait db
   ```

5. Restore into that **new, empty** database:

   ```bash
   sudo docker compose exec -T db \
     pg_restore -U postgres -d astronomy \
       --no-owner --no-privileges --exit-on-error --single-transaction \
     < backups/astronomy.dump
   ```

6. Refresh statistics and start the API:

   ```bash
   sudo docker compose exec db \
     psql -U postgres -d astronomy -c 'ANALYZE;'
   sudo docker compose up -d api
   ```

7. Verify row counts, extension/index presence, and the name/cone requests above.

Do not also run the CSV importer or the index-creation script after restoring. Do not restore over a populated database without a deliberate replacement plan and backup. A single-transaction restore rolls back on failure, avoiding a partially restored schema.

The simplest migration is between PostgreSQL 16 installations using these same Dockerfiles. Major PostgreSQL upgrades require an upgrade or dump/restore plan, not merely changing the image tag on the existing volume.

### Transfer built images when rebuilding is undesirable

For machines with compatible CPU architecture, Docker images can be saved and loaded. First find the image IDs:

```bash
sudo docker compose images
```

Assign explicit local tags using the IDs from that output:

```bash
sudo docker tag DB_IMAGE_ID first-catalog-db:transfer
sudo docker tag API_IMAGE_ID first-catalog-api:transfer
sudo docker save -o first-catalog-images.tar \
  first-catalog-db:transfer first-catalog-api:transfer
```

On the destination:

```bash
sudo docker load -i first-catalog-images.tar
```

Add matching `image: first-catalog-db:transfer` and `image: first-catalog-api:transfer` entries to the destination's `db` and `api` services, respectively. Use `docker compose up -d --no-build --pull never` to use the loaded images. For a migration, start only `db` first, restore the dump, then start `api` as described above.

Image archives **do not contain the database volume**; transfer the dump separately. An amd64 image is not automatically a native arm64 image. Rebuild on the destination architecture or publish multi-platform images when supporting both.

## Troubleshooting

### `curl: (28) Connection timed out` downloading the Docker key

Test a bounded IPv4 request:

```bash
curl -4 -I --connect-timeout 10 --max-time 30 \
  https://download.docker.com/linux/ubuntu/gpg
```

If your network needs a proxy, set the terminal proxy and explicitly pass it to `sudo` as described above. Increasing timeouts alone does not repair blocked connectivity.

### `docker-ce` has no installation candidate

Downloading the signing key does not add the repository. Check:

```bash
cat /etc/apt/sources.list.d/docker.sources
sudo apt update
apt-cache policy docker-ce
```

Resolve any repository download, signature, or unsupported-release errors first. Use the codename from `/etc/os-release`. A successful `apt-cache policy` result should show a candidate version from `download.docker.com`.

Ubuntu's `docker.io` and `docker-compose-v2` are an alternative package family where available. Do not mix that installation path with Docker CE packages.

### Compose package tries to overwrite `docker-compose`

The error naming `/usr/libexec/docker/cli-plugins/docker-compose` means Ubuntu's `docker-compose-v2` conflicts with Docker's `docker-compose-plugin`.

Run one command at a time, stopping on failure:

```bash
sudo dpkg --remove docker-compose-v2
sudo apt --fix-broken install
sudo apt install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker compose version
```

Do not force-overwrite package files to hide the conflict.

### Docker Hub or authentication TLS handshake timeout

Test both registry and token services through your proxy:

```bash
curl --proxy http://127.0.0.1:7897 \
  --connect-timeout 10 --max-time 30 \
  -o /dev/null -w 'HTTP %{http_code}\n' \
  https://registry-1.docker.io/v2/

curl --proxy http://127.0.0.1:7897 \
  --connect-timeout 10 --max-time 30 \
  -o /dev/null -w 'HTTP %{http_code}\n' \
  'https://auth.docker.io/token?scope=repository:library/postgres:pull&service=registry.docker.io'
```

Expected results: **401** for the unauthenticated registry request and **200** for the anonymous token request. Registry 401 is normal here and does not mean you must log in.

If curl succeeds but `docker pull` fails, inspect the daemon proxy. If ordinary pulls work but Compose reports `failed to fetch anonymous token`, preserve the client proxy during the build:

```bash
sudo --preserve-env=HTTP_PROXY,HTTPS_PROXY,NO_PROXY \
  docker compose up -d --build
```

Collect diagnostics if necessary:

```bash
sudo systemctl show --property=Environment docker
sudo docker buildx ls
sudo journalctl -u docker --no-pager -n 100
```

A separately selected BuildKit container may need its own proxy/network configuration. The default Docker-backed builder normally uses the Docker daemon plus the client's authentication session. A successful registry/token check does not guarantee that every redirected image-layer download host is reachable.

### `apt-get` or `pip install` fails during a build

Identify the failing stage. Failure on `FROM` is image/registry access; failure on a `RUN` instruction is inside the build environment. Follow the build-step proxy instructions and use an address reachable from that environment. Retain the full failing command output to distinguish network errors from missing packages or dependency incompatibilities.

### Connection attempts `/var/run/postgresql/.s.PGSQL.5432`

The Python process lacks `PGHOST`, so it tries a local Unix socket. Prefer running it inside the API container. For host execution set `PGHOST=127.0.0.1`, `PGPORT=5432`, `PGDATABASE=astronomy`, and `PGUSER=postgres`.

### `fe_sendauth: no password supplied`

The Python process has no nonempty `PGPASSWORD`. For host execution:

```bash
read -rsp 'PostgreSQL password: ' PGPASSWORD
export PGPASSWORD
echo
python -c 'import os; print("Password set:", bool(os.environ.get("PGPASSWORD")))'
```

Run host Python without `sudo`, which may remove the environment. For container execution, check `.env` locally and the Compose `PGPASSWORD` mapping; do not print or share the password.

### `password authentication failed for user "postgres"`

The supplied password differs from PostgreSQL's stored password. `.env` initializes credentials only for a new database volume; editing it later does not reset a database password.

For this project's standard local container authentication, connect through the container's socket:

```bash
sudo docker compose exec db psql -U postgres -d astronomy
```

At the prompt:

```text
\password postgres
```

Enter the chosen password twice, then `\q`. Update `.env` to match and recreate the API container:

```bash
sudo docker compose up -d --force-recreate api
```

If host Python is in use, set `PGPASSWORD` again in its shell. If the local socket connection also requires credentials, this reset route is unavailable; inspect the actual authentication setup rather than deleting the volume.

### Missing CSV columns, invalid values, or existing tables

- Confirm the three mappings are `FIRST`, `RAJ2000`, and `DEJ2000`.
- Confirm comma-separated UTF-8 input with a header and matching field counts.
- Numeric coordinate fields must contain decimal degrees, without units or sexagesimal formatting.
- Blank names or coordinates violate the canonical table's NOT NULL constraints; blank ancillary fields are accepted.
- If tables already exist, inspect counts and schema. A prior import may already have succeeded.
- If source changes seem ignored, rebuild the API image; it contains a copied version of the importer.

```bash
sudo docker compose exec db psql -U postgres -d astronomy -c '\dt'
```

### `position` does not exist or `spoint` is unknown

The importer does not create the spatial column/index. Check `\d sources` and `\dx` in psql. On a freshly imported database, run the pgSphere/index setup section. On a partially configured database, inspect what already exists before applying only the missing statements.

### HTTP 404, 422, or 500

- **404 at `/` or `/favicon.ico`:** expected; use `/docs` or an implemented endpoint.
- **422:** check parameter names, numeric ranges, and required fields. Radius is in degrees and must be positive.
- **500:** inspect `sudo docker compose logs --tail=100 api`. Common causes are credentials, missing tables, or missing spatial schema.
- **Name search returns no result:** encode `+` using `--data-urlencode` or `%2B`, and remember name search is exact apart from case.

### Port already in use

```bash
sudo ss -ltnp '( sport = :8000 or sport = :5432 )'
```

Stop the known conflicting process deliberately, or change the host side of the Compose mapping. For example, `127.0.0.1:8001:8000` publishes the API on host port 8001 while preserving container port 8000. If changing PostgreSQL's host port, only host clients need the new port; the API still uses `db:5432`.

### Database appears empty after moving the project

Check whether Compose is using a different project name or volume:

```bash
sudo docker compose ls
sudo docker volume ls
sudo docker compose ps -a
```

Do not delete volumes while investigating. Copying source files or images does not copy data; restore the database dump on a new machine.

## Deployment notes and references

The supplied configuration is for local use. It uses the PostgreSQL administrator account for both import and queries. Before shared or internet-facing deployment, introduce a read-only database role for the API, authentication, TLS termination, query timeouts, request limits, and managed secrets. The current API opens a database connection per query and has no pool, pagination, or application-level readiness endpoint.

The dependency file pins Python package versions, but Docker image tags and APT package versions can move. For repeatable releases, record tested image digests and extension versions, or distribute tested images. Check that pinned dependencies support any new CPU architecture before migration.

Official references:

- [Install WSL](https://learn.microsoft.com/windows/wsl/install)
- [Install Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/)
- [Docker daemon proxy configuration](https://docs.docker.com/engine/daemon/proxy/)
- [Docker build proxy arguments](https://docs.docker.com/build/building/variables/)
- [Compose environment variables](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/)
- [Compose startup order and health checks](https://docs.docker.com/compose/how-tos/startup-order/)
- [PostgreSQL official image](https://hub.docker.com/_/postgres)
- [pgSphere](https://github.com/postgrespro/pgsphere)
- [Psycopg COPY support](https://www.psycopg.org/psycopg3/docs/basic/copy)
- [FastAPI query validation](https://fastapi.tiangolo.com/tutorial/query-params-str-validations/)
