# Docker Installation and Usage

## Quick Start (Pre-built Image — Recommended)

Pre-built production images are published to GitHub Container Registry on every push to `master`.

```bash
docker run --pull always -it -p 6080:6080 -p 5900:5900 -v openoutreach_db:/app/data ghcr.io/eracle/openoutreach:latest
```

Watch the live browser (and clear any LinkedIn checkpoint) at **http://localhost:6080/vnc.html**.

The interactive onboarding will guide you through LinkedIn credentials, LLM API key, and campaign setup on first run. All data (CRM database, cookies, model blobs, embeddings) persists in the `openoutreach_db` Docker volume.

### Available Tags

| Tag | Description |
|:----|:------------|
| `latest` | Latest build from `master` |
| `sha-<commit>` | Pinned to a specific commit |
| `1.0.0` / `1.0` | Semantic version (when tagged) |

### Live Browser View (noVNC)

The container ships a noVNC web viewer for watching the automation live — and for clearing a LinkedIn security checkpoint by hand when one appears. Open it in any browser (no password):

```
http://localhost:6080/vnc.html
```

Prefer a native VNC client? One is also exposed on `localhost:5900`. On Linux with `vinagre`:
```bash
vinagre vnc://127.0.0.1:5900
```

> Both ports must be published for the viewers to work — see the `-p 6080:6080 -p 5900:5900` flags in the run command below.

### Stopping & Restarting

```bash
# Find the container
docker ps

# Stop it
docker stop <container-id>

# Restart (data persists in the openoutreach_db volume)
docker run --pull always -it -p 6080:6080 -p 5900:5900 -v openoutreach_db:/app/data ghcr.io/eracle/openoutreach:latest
```

---

## Build from Source (Docker Compose)

For development or customization, you can build the image locally. The compose file (`local.yml`)
mounts the entire project directory into the container for live code editing.

### Prerequisites

- [Make](https://www.gnu.org/software/make/)
- [Docker](https://www.docker.com/)
- [Docker Compose](https://docs.docker.com/compose/)

### Build & Run

```bash
git clone https://github.com/eracle/OpenOutreach.git
cd OpenOutreach

# Build and start
make up
```

This builds the Docker image from source with `BUILD_ENV=local` (includes test dependencies), starts Postgres (`db` service on port 5432, credentials `openoutreach` / `openoutreach` / `openoutreach`), and starts the daemon. For host-side `make setup` / `make admin`, run `make db` first so Postgres is reachable on `localhost:5432`.

**Note:** The compose file uses `HOST_UID` / `HOST_GID` environment variables (defaulting to 1000)
for file ownership. If your host UID differs from 1000, set them explicitly:

```bash
HOST_UID=$(id -u) HOST_GID=$(id -g) make up
```

### Useful Commands

| Command | Description |
|:--------|:------------|
| `make build` | Build the Docker image without starting |
| `make up` | Build and start the service |
| `make stop` | Stop the running containers |
| `make logs` | Follow application logs |
| `make up-view` | Start + open VNC viewer (Linux, requires `vinagre`) |
| `make view` | Open VNC viewer standalone (requires `vinagre`) |
| `make docker-test` | Run the test suite in Docker |

### VNC with Docker Compose

The live browser view is exposed two ways: the noVNC web viewer at **http://localhost:6080/vnc.html** (open in any browser), or the native VNC port `localhost:5900`. Use `make up-view` to auto-open the native viewer, or connect manually with any VNC client.

### Volume Mounts

The pre-built `docker run` command uses a named Docker volume (`openoutreach_db`) mounted at `/app/data` for data persistence (cookies/caches; older images used SQLite there). The compose setup (`local.yml`) mounts the entire repo `.:/app` for live code editing and persists Postgres in the `postgres_data` volume.
