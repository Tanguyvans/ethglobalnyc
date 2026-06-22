# Prematch Data Pipeline

The benchmark collection pipeline is intentionally layered. Raw provider
snapshots are saved first, then normalized records are derived from those raw
files, then KG-ready claims are generated from the normalized layer.

## Directory Layout

Each match collection should use this layout:

```text
<match_run>/
  collection_manifest.json
  raw/
    google_news/
    gdelt/
    scrapecreators_x/
    polymarket/
      gamma_public_search.json
      clob/
  normalized/
    prematch_documents.json
  kg/
    prematch_kg_source.json
  polymarket_kg/
    <match_slug>/
      findings.json
      world_graph.json
      knowledge_views.json
  reports/
    prematch_quality_report.md
```

## Rules

- `raw/` is immutable evidence. Do not edit these files after collection.
- `normalized/` may be regenerated from `raw/`.
- `kg/` may be regenerated from `normalized/`.
- `polymarket_kg/` is produced by the existing KG scouting module; its raw
  Gamma/CLOB inputs are also saved under `raw/polymarket/`.
- Benchmark datasets should be built only after the match result is known, and
  only from sources whose `available_at_utc` is earlier than the configured
  prediction cutoff.

## Cleanup Policy

Keep:

- raw provider responses;
- normalized documents;
- KG-ready source files;
- quality reports and collection manifests.

Delete:

- dry-run manifests;
- failed one-off probes that are not linked from a collection manifest;
- raw files from obsolete hardcoded queries that do not mention the match teams;
- Python caches.
