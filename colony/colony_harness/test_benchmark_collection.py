"""Tests for raw benchmark source collection."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from colony.collect_benchmark_data import CollectionSource, collect_sources


class BenchmarkCollectionTests(unittest.TestCase):
    def test_collect_local_source_writes_manifest_hash_and_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "source.json"
            source_bytes = b'{"hello": "benchmark"}\n'
            source_path.write_bytes(source_bytes)

            manifest = collect_sources(
                sources=[
                    CollectionSource(
                        source_id="local_fixture",
                        source_type="fixture",
                        locator=str(source_path),
                        output_name="fixture.json",
                        kind="local_file",
                        description="fixture test",
                    )
                ],
                output_dir=root / "out",
            )

            manifest_path = root / "out" / "collection_manifest.json"
            self.assertTrue(manifest_path.exists())
            persisted_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["summary"], {"total": 1, "ok": 1, "failed": 0})
            row = persisted_manifest["sources"][0]
            self.assertEqual(row["status"], "ok")
            self.assertEqual(row["sha256"], hashlib.sha256(source_bytes).hexdigest())
            self.assertTrue(row["collected_at_utc"])
            self.assertEqual((root / "out" / "fixture.json").read_bytes(), source_bytes)


if __name__ == "__main__":
    unittest.main()
