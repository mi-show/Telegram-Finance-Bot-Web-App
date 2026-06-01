#!/usr/bin/env python3
"""Split Chart.js UMD source into browser chunks and regenerate chart-factory bootstrap.

Example:
  python scripts/split_chart_factory.py \
    --source third_party/chart.umd.min.js \
    --target-dir app/web/static/vendor/chart \
    --chunk-size 55000
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path


BOOTSTRAP_TEMPLATE = """(function(globalScope) {
  \"use strict\";

  class ChartFactoryAssembler {
    constructor(scope) {
      this.scope = scope;
      this.chunkStoreKey = \"__ChartFactoryChunkStore\";
    }

    readChunks() {
      const chunks = this.scope[this.chunkStoreKey];
      if (!Array.isArray(chunks) || chunks.length === 0) {
        throw new Error(\"Chart factory chunks are missing.\");
      }
      return chunks;
    }

    evaluateSource(source) {
      (0, eval)(source);
      const factory = this.scope.__ChartUmdFactory;
      if (typeof factory !== \"function\") {
        throw new Error(\"Chart factory did not initialize.\");
      }
      return factory;
    }

    cleanup() {
      delete this.scope[this.chunkStoreKey];
    }

    bootstrap() {
      const source = this.readChunks().join(\"\");
      try {
        return this.evaluateSource(source);
      } finally {
        this.cleanup();
      }
    }
  }

  const assembler = new ChartFactoryAssembler(globalScope);
  assembler.bootstrap();
})(window);
"""


@dataclass(frozen=True)
class SplitConfig:
  source: Path
  target_dir: Path
  chunk_size: int
  chunk_folder_name: str = "factory_chunks"
  bootstrap_filename: str = "chart-factory.min.js"

  @property
  def chunk_dir(self) -> Path:
    return self.target_dir / self.chunk_folder_name

  @property
  def bootstrap_file(self) -> Path:
    return self.target_dir / self.bootstrap_filename


class ChartFactorySplitter:
  def __init__(self, config: SplitConfig) -> None:
    self.config = config

  def run(self) -> int:
    source_text = self._read_source()
    chunks = self._split(source_text)
    self._write_chunks(chunks)
    self._write_bootstrap()

    print(f"source: {self.config.source}")
    print(f"target: {self.config.target_dir}")
    print(f"chunk_dir: {self.config.chunk_dir}")
    print(f"bootstrap: {self.config.bootstrap_file}")
    print(f"chunks: {len(chunks)}")
    return len(chunks)

  def _read_source(self) -> str:
    if not self.config.source.exists():
      raise FileNotFoundError(f"source file not found: {self.config.source}")

    return self.config.source.read_text(encoding="utf-8")

  def _split(self, source_text: str) -> list[str]:
    if self.config.chunk_size <= 0:
      raise ValueError("chunk-size must be > 0")

    return [
      source_text[i : i + self.config.chunk_size]
      for i in range(0, len(source_text), self.config.chunk_size)
    ]

  def _write_chunks(self, chunks: list[str]) -> None:
    self.config.chunk_dir.mkdir(parents=True, exist_ok=True)

    for old_chunk in self.config.chunk_dir.glob("chunk-*.js"):
      old_chunk.unlink()

    for index, chunk in enumerate(chunks, start=1):
      chunk_file = self.config.chunk_dir / f"chunk-{index:02d}.js"
      chunk_file.write_text(
        "window.__ChartFactoryChunkStore = window.__ChartFactoryChunkStore || [];\n"
        + f"window.__ChartFactoryChunkStore.push({json.dumps(chunk)});\n",
        encoding="utf-8",
      )

  def _write_bootstrap(self) -> None:
    self.config.bootstrap_file.write_text(BOOTSTRAP_TEMPLATE, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    description="Split Chart.js UMD source into chunk files and bootstrap loader."
  )
  parser.add_argument(
    "--source",
    required=True,
    type=Path,
    help="Path to original chart UMD source (single file).",
  )
  parser.add_argument(
    "--target-dir",
    default=Path("app/web/static/vendor/chart"),
    type=Path,
    help="Directory where factory_chunks and chart-factory.min.js will be written.",
  )
  parser.add_argument(
    "--chunk-size",
    default=55000,
    type=int,
    help="Maximum number of characters per chunk file.",
  )
  return parser


def main() -> int:
  args = build_parser().parse_args()
  config = SplitConfig(
    source=args.source,
    target_dir=args.target_dir,
    chunk_size=args.chunk_size,
  )
  splitter = ChartFactorySplitter(config)
  splitter.run()
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
