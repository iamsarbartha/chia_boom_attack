"""Build BOOM Verilator RTL and ask Gemini to report its cache architecture."""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from chia.base.ChiaFunction import get
from chia.base.llm_call import QueryResult
from chia.base.tools.ChiaTool import ChiaTool
from chia.chipyard.chisel_build_node import ChiselBuildNode
from chia.chipyard.state_def import BuildArtifact, BuildTarget
from chia.models.vertex import VertexGeminiLLM


CHIPYARD_PATH = Path("/home/ray/chipyard")
BOOM_CONFIG = os.environ.get("CHIASTRA_BOOM_CONFIG", "MegaBoomV3Config")
GEMINI_MODEL = os.environ.get(
    "CHIASTRA_GEMINI_MODEL", "gemini-3.5-flash-lite"
)
REPORT_PATH = Path(
    os.environ.get("CHIASTRA_REPORT", "/tmp/chiastra/boom_cache_report.md")
)
MAX_TOOL_OUTPUT_CHARS = 40_000


class VerilatorSourceTool(ChiaTool):
    """Read-only, path-confined access to generated Verilator RTL."""

    _ALLOWED_SUFFIXES = {".v", ".sv", ".conf"}

    def setup(self, root_dir: str):
        self.root_dir = Path(root_dir).resolve()
        self.mcp.add_tool(self.list_files, name=f"{self.name}_list_files")
        self.mcp.add_tool(self.search_text, name=f"{self.name}_search_text")
        self.mcp.add_tool(self.read_file, name=f"{self.name}_read_file")

    def _source_files(self) -> list[Path]:
        if not self.root_dir.is_dir():
            return []
        return sorted(
            path
            for path in self.root_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in self._ALLOWED_SUFFIXES
        )

    def _resolve_file(self, relative_path: str) -> Path:
        candidate = (self.root_dir / relative_path).resolve()
        try:
            candidate.relative_to(self.root_dir)
        except ValueError as exc:
            raise ValueError(
                "Path must stay inside the generated-source directory"
            ) from exc
        if candidate.suffix.lower() not in self._ALLOWED_SUFFIXES:
            raise ValueError("Only .v, .sv, and .conf files may be read")
        if not candidate.is_file():
            raise FileNotFoundError(relative_path)
        return candidate

    def list_files(self, glob: str = "*", limit: int = 200) -> str:
        """List source files matching a shell glob, up to a limit of 500."""
        limit = max(1, min(limit, 500))
        matches = []
        for path in self._source_files():
            relative = path.relative_to(self.root_dir).as_posix()
            if fnmatch.fnmatch(relative, glob) or fnmatch.fnmatch(path.name, glob):
                matches.append(relative)
                if len(matches) >= limit:
                    break
        return "\n".join(matches) if matches else f"No files matched {glob!r}."

    def search_text(
        self, text: str, glob: str = "*", max_matches: int = 100
    ) -> str:
        """Search sources for literal text; return file:line:source evidence."""
        if not text or len(text) > 200:
            raise ValueError("Search text must contain 1-200 characters")
        max_matches = max(1, min(max_matches, 200))
        needle = text.casefold()
        results = []
        output_chars = 0
        for path in self._source_files():
            relative = path.relative_to(self.root_dir).as_posix()
            if not (
                fnmatch.fnmatch(relative, glob)
                or fnmatch.fnmatch(path.name, glob)
            ):
                continue
            with path.open("r", encoding="utf-8", errors="replace") as source:
                for line_number, line in enumerate(source, start=1):
                    if needle not in line.casefold():
                        continue
                    result = f"{relative}:{line_number}: {line.rstrip()}"
                    results.append(result)
                    output_chars += len(result) + 1
                    if (
                        len(results) >= max_matches
                        or output_chars >= MAX_TOOL_OUTPUT_CHARS
                    ):
                        return "\n".join(results)
        return "\n".join(results) if results else f"No matches for {text!r}."

    def read_file(
        self,
        relative_path: str,
        start_line: int = 1,
        end_line: int = 250,
    ) -> str:
        """Read a line-numbered file slice, returning at most 400 lines."""
        path = self._resolve_file(relative_path)
        start_line = max(1, start_line)
        end_line = max(start_line, min(end_line, start_line + 399))
        selected = []
        with path.open("r", encoding="utf-8", errors="replace") as source:
            for line_number, line in enumerate(source, start=1):
                if line_number > end_line:
                    break
                if line_number >= start_line:
                    selected.append(f"{line_number}: {line.rstrip()}")
        return "\n".join(selected) if selected else "No lines in that range."


def generated_source_dir(artifact: BuildArtifact) -> Path:
    """Return the generated output directory for a successful build."""
    return (
        CHIPYARD_PATH
        / "sims"
        / "verilator"
        / "generated-src"
        / f"{artifact.config_package}.harness.TestHarness.{artifact.config}"
    )


REPORT_PROMPT = """\
Inspect the generated Verilator RTL using the verilator_source tools and write a
technical report describing the cache architecture of this BOOM processor.

Requirements:
1. Base the report on tool evidence, not prior BOOM knowledge. Start by listing
   files and searching for cache, icache, dcache, L2, bank, set, way, tag, data,
   miss/MSHR, and TileLink signals.
2. Identify the exact processor/configuration represented by the evidence.
3. Cover instruction, data, and shared/outer caches when present: capacity or
   derivable SRAM dimensions, sets, ways, line size, banking, ports, miss
   handling, replacement/coherence clues, and hierarchy connections.
4. Label values Observed, Derived, or Unknown. Show capacity arithmetic and do
   not invent parameters absent from the generated RTL.
5. Cite every material claim as relative/file:line or a short line range.
6. End with a compact hierarchy summary and cache-parameter table.

Return only the Markdown report. Do not edit files.
"""


def main() -> None:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        raise RuntimeError("Set GOOGLE_CLOUD_PROJECT before submitting this job")

    print(f"Building {BOOM_CONFIG} and generating Verilator RTL...")
    builder = ChiselBuildNode(
        str(CHIPYARD_PATH),
        BOOM_CONFIG,
        target=BuildTarget.VERILATOR,
        make_jobs=int(os.environ.get("CHIASTRA_MAKE_JOBS", "32")),
        timeout_seconds=int(os.environ.get("CHIASTRA_BUILD_TIMEOUT", "3600")),
    )
    artifact: BuildArtifact = get(builder.build.chia_remote(builder))
    if not artifact.success:
        raise RuntimeError(
            f"BOOM build failed with exit code {artifact.returncode}:\n"
            f"{artifact.stderr[-4000:]}"
        )

    source_dir = generated_source_dir(artifact)
    print(f"Deploying read-only source tool at {source_dir}...")
    source_tool = VerilatorSourceTool(
        "verilator_source",
        str(source_dir),
        task_options={"resources": {"chipyard": 0.01}},
    )

    try:
        llm = VertexGeminiLLM(
            model=GEMINI_MODEL,
            project=project,
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
            system_message=(
                "You are a senior CPU microarchitect. Be evidence-driven and "
                "explicit about uncertainty when interpreting generated RTL."
            ),
            timeout_seconds=int(os.environ.get("CHIASTRA_LLM_TIMEOUT", "1200")),
            max_tokens=int(os.environ.get("CHIASTRA_MAX_TOKENS", "16000")),
        )
        response: QueryResult = get(
            llm.prompt.chia_remote(llm, REPORT_PROMPT, tools=[source_tool])
        )
        if not response.success:
            raise RuntimeError(
                f"Gemini did not produce a report (return code {response.returncode})"
            )
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(response.result, encoding="utf-8")
        print(f"Cache architecture report written to {REPORT_PATH.resolve()}")
        print(response.result)
    finally:
        source_tool.stop()


if __name__ == "__main__":
    main()
