# BigSolDB MCP Server

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server for **BigSolDB v2.1** — the largest experimental organic solubility database (~112K records, 218 solvents). Enables AI assistants such as Claude to query solubility data directly in conversation.

## Available Tools

| Tool | Description |
|------|-------------|
| `search_by_name` | Search by compound name (case-insensitive substring match) |
| `search_by_smiles` | Search by exact solute SMILES string |
| `search_by_cas` | Search by CAS registry number |
| `search_by_solvent` | All records for a given solvent, with optional LogS range filter |
| `get_solubility_stats` | LogS statistics (mean, std, min, max) for a compound |
| `list_solvents` | List all 218 solvents present in the database |
| `search_fda_approved` | Records for FDA-approved compounds only |

## Quickstart

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the server
python server.py --csv BigSolDBv2_1.csv --port 8000
```

The server will be available at `http://localhost:8000/sse`.

## Deployment

### Railway (recommended)

```bash
# Add a Procfile
echo "web: python server.py --csv BigSolDBv2_1.csv --port $PORT" > Procfile

railway up
```

Environment variable: `BIGSOLDB_CSV=/path/to/BigSolDBv2_1.csv`

### Fly.io

```bash
fly launch
fly deploy
```

`fly.toml`:
```toml
[env]
  BIGSOLDB_CSV = "/data/BigSolDBv2_1.csv"

[mounts]
  source = "bigsoldb_data"
  destination = "/data"
```

### Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY server.py .
COPY BigSolDBv2_1.csv .
ENV BIGSOLDB_CSV=BigSolDBv2_1.csv
CMD ["python", "server.py", "--port", "8000"]
```

```bash
docker build -t bigsoldb-mcp .
docker run -p 8000:8000 bigsoldb-mcp
```

## Connecting to Claude.ai

1. Go to **Settings → Connectors → Add custom connector**
2. Enter your deployment URL: `https://your-domain.com/sse`
3. Done — Claude will have access to all 7 tools

## Notes

- The CSV is loaded into memory (~100 MB); search is linear over 112K rows, which is fast enough for interactive use.
- For production workloads, consider adding a SQLite index on SMILES, CAS, and compound name to reduce search from O(n) to O(log n).
- All temperatures are stored in Kelvin.

## Citation

If you use BigSolDB in your work, please cite the original publication:

> Krasnov, L. et al. BigSolDB 2.0, dataset of solubility values for organic compounds in different solvents at various temperatures. *Scientific Data* (2025). https://doi.org/10.1038/s41597-025-05559-8
