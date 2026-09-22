"""Build BOOM and run the Google ADK vulnerability-exploration workflow."""

from __future__ import annotations

import asyncio
import fnmatch
import json
import os
import re
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from google.genai import types

from chia.base.ChiaFunction import get
from chia.base.llm_call import QueryResult
from chia.base.tools.ChiaTool import ChiaTool
from chia.chipyard.chisel_build_node import ChiselBuildNode
from chia.chipyard.riscv_build_node import RiscvBuildNode
from chia.chipyard.state_def import BuildArtifact, BuildTarget
from chia.chipyard.verilator_run_node import VerilatorRunNode
from chia.models.vertex import VertexGeminiLLM


CHIPYARD_PATH = Path("/home/ray/chipyard")
BOOM_CONFIG = os.environ.get("CHIASTRA_BOOM_CONFIG", "MegaBoomV3Config")
GEMINI_MODEL = os.environ.get("CHIASTRA_GEMINI_MODEL", "gemini-3.5-flash-lite")
REPORT_PATH = Path(os.environ.get("CHIASTRA_REPORT", "/tmp/chiastra/boom_cache_report.md"))
OUTPUT_DIR = Path(os.environ.get("CHIASTRA_OUTPUT_DIR", str(REPORT_PATH.parent)))
RISCV_WORK_DIR = os.environ.get("CHIASTRA_RISCV_WORK_DIR", "/tmp/chiastra/riscv")
VERILATOR_WORK_DIR = os.environ.get("CHIASTRA_VERILATOR_WORK_DIR", "/tmp/chiastra/verilator")
SIM_TIMEOUT_CYCLES = int(os.environ.get("CHIASTRA_SIM_TIMEOUT_CYCLES", "10000000"))
SIM_TIMEOUT_SECONDS = int(os.environ.get("CHIASTRA_SIM_TIMEOUT", "600"))
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
        return sorted(path for path in self.root_dir.rglob("*")
                      if path.is_file() and path.suffix.lower() in self._ALLOWED_SUFFIXES)

    def _resolve_file(self, relative_path: str) -> Path:
        candidate = (self.root_dir / relative_path).resolve()
        try:
            candidate.relative_to(self.root_dir)
        except ValueError as exc:
            raise ValueError("Path must stay inside the generated-source directory") from exc
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

    def search_text(self, text: str, glob: str = "*", max_matches: int = 100) -> str:
        """Search sources for literal text; return file:line:source evidence."""
        if not text or len(text) > 200:
            raise ValueError("Search text must contain 1-200 characters")
        max_matches = max(1, min(max_matches, 200))
        needle = text.casefold()
        results = []
        output_chars = 0
        for path in self._source_files():
            relative = path.relative_to(self.root_dir).as_posix()
            if not (fnmatch.fnmatch(relative, glob) or fnmatch.fnmatch(path.name, glob)):
                continue
            with path.open("r", encoding="utf-8", errors="replace") as source:
                for line_number, line in enumerate(source, start=1):
                    if needle not in line.casefold():
                        continue
                    result = f"{relative}:{line_number}: {line.rstrip()}"
                    results.append(result)
                    output_chars += len(result) + 1
                    if len(results) >= max_matches or output_chars >= MAX_TOOL_OUTPUT_CHARS:
                        return "\n".join(results)
        return "\n".join(results) if results else f"No matches for {text!r}."

    def read_file(self, relative_path: str, start_line: int = 1, end_line: int = 250) -> str:
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
    return (CHIPYARD_PATH / "sims" / "verilator" / "generated-src"
            / f"{artifact.config_package}.harness.TestHarness.{artifact.config}")


REPORT_PROMPT = """\
Inspect the generated Verilator RTL using the verilator_source tools and write a
technical report describing the cache architecture of this BOOM processor.

Requirements:
1. Base the report on tool evidence, not prior BOOM knowledge. Start by listing
   files and searching for cache, icache, dcache, L2, bank, set, way, tag, data,
   miss/MSHR, and TileLink signals.
2. Identify the exact processor/configuration represented by the evidence.
3. Cover instruction, data, and shared/outer caches when present.
4. Label values Observed, Derived, or Unknown. Show capacity arithmetic.
5. Cite every material claim as relative/file:line or a short line range.
6. End with a compact hierarchy summary and cache-parameter table.

Return only the Markdown report. Do not edit files.
"""



def _event_text(event: Any) -> str:
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    return "".join(getattr(part, "text", "") or "" for part in parts)


def _record_adk_event(
    trajectory: dict[str, Any], event: Any, trace_path: Path
) -> tuple[str, bool]:
    """Persist the complete ADK event and any agent text before continuing."""
    text = _event_text(event)
    is_final = event.is_final_response()
    trajectory["events"].append({
        **event.model_dump(mode="json", exclude_none=True),
        "is_final_response": is_final,
    })
    if text:
        trajectory["responses"].append({
            "author": event.author,
            "event_id": event.id,
            "is_final_response": is_final,
            "text": text,
        })

    temporary_path = trace_path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(trajectory, indent=2), encoding="utf-8"
    )
    temporary_path.replace(trace_path)
    return text, is_final


def _adk_event_summary(event: Any) -> str:
    parts = getattr(getattr(event, "content", None), "parts", None) or []
    calls = [p.function_call.name for p in parts
             if getattr(p, "function_call", None)]
    responses = [p.function_response.name for p in parts
                 if getattr(p, "function_response", None)]
    return (
        f"author={event.author} final={event.is_final_response()} "
        f"finish_reason={event.finish_reason} calls={calls} "
        f"responses={responses} text_length={len(_event_text(event))} "
        f"error={event.error_code}: {event.error_message}"
    )


async def run_with_progress(
    runner: Any, *, user_id: str, session_id: str, new_message: Any,
    preview_chars: int = 800,
) -> AsyncIterator[Any]:
    """Print outer-runner events as they arrive, yielding each unchanged.

    Nested AgentTool runners expose their calls/results here, not their internal
    events. This reports event progress; it does not enable token streaming.
    """
    if preview_chars < 0:
        raise ValueError("preview_chars must be nonnegative")
    started = time.monotonic()
    count = 0
    print(f"[ADK] Starting session={session_id}", flush=True)
    try:
        async for event in runner.run_async(
            user_id=user_id, session_id=session_id, new_message=new_message
        ):
            count += 1
            prefix = f"[ADK #{count} +{time.monotonic() - started:.1f}s]"
            print(f"{prefix} {_adk_event_summary(event)}", flush=True)
            parts = getattr(getattr(event, "content", None), "parts", None) or []
            for part in parts:
                if getattr(part, "thought", False):
                    continue
                details = []
                if call := getattr(part, "function_call", None):
                    details.append((f"CALL {call.name}", call.args))
                if response := getattr(part, "function_response", None):
                    details.append((f"RESULT {response.name}", response.response))
                if text := getattr(part, "text", None):
                    details.append(("TEXT", text))
                for label, value in details:
                    if preview_chars:
                        payload = value if isinstance(value, str) else json.dumps(
                            value, ensure_ascii=False, default=str
                        )
                        preview = payload[:preview_chars]
                        if len(payload) > preview_chars:
                            preview += " … [truncated; full event in adk_trajectory.json]"
                        print(f"{prefix} {label}: {preview}", flush=True)
            yield event
    except Exception as exc:
        print(f"[ADK] Event stream failed: {type(exc).__name__}: {exc}", flush=True)
        raise
    else:
        print(
            f"[ADK] Event stream ended after {count} events "
            f"in {time.monotonic() - started:.1f}s", flush=True,
        )


async def run_adk_agent(agent: Any, prompt: str, app_name: str) -> str:
    """Run one ADK agent in an isolated in-memory session."""
    try:
        from google.adk.apps import App
        from google.adk.runners import InMemoryRunner
    except ImportError as exc:
        raise RuntimeError("Google ADK is required; reinstall the project") from exc

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    trace_path = OUTPUT_DIR / "adk_trajectory.json"
    trajectory: dict[str, Any] = {
        "app_name": app_name,
        "events": [],
        "responses": [],
    }
    trace_path.write_text(json.dumps(trajectory, indent=2), encoding="utf-8")

    runner = InMemoryRunner(app=App(name=app_name, root_agent=agent))
    session = await runner.session_service.create_session(
        app_name=app_name, user_id="chiastra"
    )
    message = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
    final_text = ""
    event_count = 0
    last_event = "none"
    async for event in run_with_progress(
        runner, user_id="chiastra", session_id=session.id, new_message=message,
        preview_chars=int(os.environ.get("CHIASTRA_ADK_PREVIEW_CHARS", "800")),
    ):
        event_count += 1
        text, is_final = _record_adk_event(trajectory, event, trace_path)
        last_event = _adk_event_summary(event)
        if text and event.author == agent.name and is_final:
            final_text = text
    if not final_text:
        raise RuntimeError(
            f"ADK agent {agent.name} produced no final text after "
            f"{event_count} events; last event: {last_event}"
        )
    return final_text



def _concise_record(record: dict[str, Any]) -> dict[str, Any]:
    verbose = {"build_stdout", "build_stderr", "objdump", "simulation_log", "simulation_out"}
    concise = {key: value for key, value in record.items() if key not in verbose}
    for key in ("build_stdout", "build_stderr", "simulation_log", "simulation_out"):
        if key in record:
            concise[f"{key}_tail"] = str(record[key])[-3000:]
    return concise


def make_boom_execution_tool(
    simulator: BuildArtifact, execution_records: dict[str, dict[str, Any]]
):
    """Expose single and batched C-to-BOOM tools to the ADK subagents."""

    def execute_boom_program(
        source_code: str, program_name: str, process_id: int = 0
    ) -> dict[str, Any]:
        """Compile and run one bare-metal C experiment on BOOM Verilator.

        Args:
            source_code: Complete C source for the experiment.
            program_name: Short alphanumeric experiment name used for artifacts.
            process_id: Optional CHIASTRA_PROCESS_ID value (0, 1, or 2).

        Returns:
            Build and simulation evidence. passed means simulator success.
        """
        if not re.fullmatch(r"[A-Za-z0-9_]{1,48}", program_name):
            return {"passed": False, "error": "program_name must be a short identifier"}
        if process_id not in (0, 1, 2):
            return {"passed": False, "error": "process_id must be 0, 1, or 2"}
        if program_name in execution_records:
            return {"passed": False, "error": "program_name was already executed"}
        if not source_code or len(source_code) > 100_000:
            return {"passed": False, "error": "source must contain 1-100000 characters"}

        flags = "-O2"
        if process_id:
            flags += f" -DCHIASTRA_PROCESS_ID={process_id}"
        build_node = RiscvBuildNode(timeout_seconds=300)
        built = get(build_node.build.chia_remote(
            build_node, source_code.encode(), program_name, RISCV_WORK_DIR,
            target="verilator", extra_cflags=flags, include_dump=True,
        ))
        record: dict[str, Any] = {
            "program_name": program_name,
            "process_id": process_id,
            "build_success": built.success,
            "build_returncode": built.returncode,
            "build_stderr_tail": built.stderr[-3000:],
            "objdump_tail": built.dump[-3000:],
        }
        if not built.success:
            record.update(passed=False, reason="RISC-V compilation failed")
            execution_records[program_name] = record
            return _concise_record(record)

        run_node = VerilatorRunNode()
        run = get(run_node.run.chia_remote(
            run_node, simulator, built.binary_content, built.binary_name,
            VERILATOR_WORK_DIR, plusargs={"+loadmem": built.binary_name},
            timeout_cycles=SIM_TIMEOUT_CYCLES,
            timeout_seconds=SIM_TIMEOUT_SECONDS, verbose=False,
        ))
        record.update(
            passed=run.success,
            simulation_returncode=run.returncode,
            simulation_log=run.log,
            simulation_out=run.out,
        )
        execution_records[program_name] = record
        return _concise_record(record)

    def execute_boom_program_batch(
        experiments: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build and run independent experiments concurrently through Ray.

        All builds are submitted before waiting; then all successful
        simulations are submitted before waiting. Ray can therefore place
        independent work on multiple custom-resource workers.
        """
        if not experiments:
            return []
        if len(experiments) > 32:
            return [{"passed": False, "error": "at most 32 experiments per batch"}]

        prepared: list[tuple[str, str, int]] = []
        results: list[dict[str, Any] | None] = []
        seen: set[str] = set()
        for experiment in experiments:
            source_code = experiment.get("source_code", "")
            program_name = experiment.get("program_name", "")
            process_id = experiment.get("process_id", 0)
            valid = (
                isinstance(source_code, str)
                and bool(re.fullmatch(r"[A-Za-z0-9_]{1,48}", program_name))
                and process_id in (0, 1, 2)
                and bool(source_code)
                and len(source_code) <= 100_000
                and program_name not in seen
                and program_name not in execution_records
            )
            if not valid:
                results.append({
                    "program_name": program_name,
                    "passed": False,
                    "error": "invalid, duplicate, or already executed experiment",
                })
                continue
            seen.add(program_name)
            prepared.append((source_code, program_name, process_id))
            results.append(None)

        build_nodes = [RiscvBuildNode(timeout_seconds=300) for _ in prepared]
        build_refs = [
            node.build.chia_remote(
                node, source.encode(), name, RISCV_WORK_DIR,
                target="verilator",
                extra_cflags=("-O2" if process_id == 0
                              else f"-O2 -DCHIASTRA_PROCESS_ID={process_id}"),
                include_dump=True,
            )
            for node, (source, name, process_id) in zip(build_nodes, prepared)
        ]
        built_results = get(build_refs)

        run_refs = []
        runnable: list[tuple[int, int]] = []
        build_index = 0
        for result_index, result in enumerate(results):
            if result is not None:
                continue
            built = built_results[build_index]
            name = prepared[build_index][1]
            if not built.success:
                record = {
                    "program_name": name,
                    "process_id": prepared[build_index][2],
                    "build_success": False,
                    "build_returncode": built.returncode,
                    "build_stderr_tail": built.stderr[-3000:],
                    "objdump_tail": built.dump[-3000:],
                    "passed": False,
                    "reason": "RISC-V compilation failed",
                }
                execution_records[name] = record
                results[result_index] = _concise_record(record)
            else:
                run_node = VerilatorRunNode()
                run_refs.append(run_node.run.chia_remote(
                    run_node, simulator, built.binary_content, built.binary_name,
                    VERILATOR_WORK_DIR, plusargs={"+loadmem": built.binary_name},
                    timeout_cycles=SIM_TIMEOUT_CYCLES,
                    timeout_seconds=SIM_TIMEOUT_SECONDS, verbose=False,
                ))
                runnable.append((result_index, build_index))
            build_index += 1

        run_results = get(run_refs) if run_refs else []
        for run_result, (result_index, built_index) in zip(run_results, runnable):
            built = built_results[built_index]
            name = prepared[built_index][1]
            record = {
                "program_name": name,
                "process_id": prepared[built_index][2],
                "build_success": True,
                "build_returncode": built.returncode,
                "build_stderr_tail": built.stderr[-3000:],
                "objdump_tail": built.dump[-3000:],
                "passed": run_result.success,
                "simulation_returncode": run_result.returncode,
                "simulation_log": run_result.log,
                "simulation_out": run_result.out,
            }
            execution_records[name] = record
            results[result_index] = _concise_record(record)

        return [result for result in results if result is not None]

    return execute_boom_program, execute_boom_program_batch





def main() -> None:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        raise RuntimeError("Set GOOGLE_CLOUD_PROJECT before submitting this job")
    os.environ.setdefault("GOOGLE_GENAI_USE_ENTERPRISE", "TRUE")
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")

    print(f"Building {BOOM_CONFIG} and generating Verilator RTL...")
    builder = ChiselBuildNode(
        str(CHIPYARD_PATH), BOOM_CONFIG, target=BuildTarget.VERILATOR,
        make_jobs=int(os.environ.get("CHIASTRA_MAKE_JOBS", "32")),
        timeout_seconds=int(os.environ.get("CHIASTRA_BUILD_TIMEOUT", "3600")),
    )
    artifact: BuildArtifact = get(builder.build.chia_remote(builder))
    if not artifact.success:
        raise RuntimeError(
            f"BOOM build failed with exit code {artifact.returncode}:\n"
            f"{artifact.stderr[-4000:]}")

    source_dir = generated_source_dir(artifact)
    print(f"Deploying read-only source tool at {source_dir}...")
    source_tool = VerilatorSourceTool(
        "verilator_source", str(source_dir),
        task_options={"resources": {"chipyard": 0.01}},
    )
    try:
        llm = VertexGeminiLLM(
            model=GEMINI_MODEL, project=project,
            location=os.environ["GOOGLE_CLOUD_LOCATION"],
            system_message=(
                "You are a senior CPU microarchitect. Be evidence-driven and "
                "explicit about uncertainty when interpreting generated RTL."),
            timeout_seconds=int(os.environ.get("CHIASTRA_LLM_TIMEOUT", "1200")),
            max_tokens=int(os.environ.get("CHIASTRA_MAX_TOKENS", "16000")),
            # Plain dicts serialize safely from the Ray driver to the worker.
            client_kwargs={"http_options": {"retry_options": {
                "attempts": 6,
                "initial_delay": 5,
                "max_delay": 60,
                "jitter": 1,
                "http_status_codes": [429],
            }}},
        )
        response: QueryResult = get(
            llm.prompt.chia_remote(llm, REPORT_PROMPT, tools=[source_tool]))
        if not response.success:
            raise RuntimeError(
                f"Gemini did not produce a report (return code {response.returncode})")
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(response.result, encoding="utf-8")
        print(f"Cache architecture report written to {REPORT_PATH.resolve()}")
    finally:
        source_tool.stop()


    # Connect the research, generator, and validator subagents to the built
    # simulator through a controlled compile-and-run tool.
    try:
        import google_agent as agent_infra
    except ImportError as exc:
        raise RuntimeError("google_agent.py and google-adk are required") from exc

    execution_records: dict[str, dict[str, Any]] = {}
    execution_tool, execution_batch_tool = make_boom_execution_tool(
        artifact, execution_records
    )
    for agent in (
        agent_infra.vulnerability_generator,
        agent_infra.validator,
        agent_infra.root_agent,
    ):
        agent.tools.append(execution_tool)
        agent.tools.append(execution_batch_tool)

    exploration_prompt = f"""\
	Run the complete BOOM cache-vulnerability exploration workflow against the
	already-built {BOOM_CONFIG} Verilator target. First delegate the cache report
	below to vulnerability_research_agent_2 and use its frozen hypothesis and
	success criteria as the experiment specification. Then delegate source
	generation to vulnerability_generator. The validator must compile every
	generator-produced C/assembly experiment with the RISC-V build tool and run
	the resulting binaries in the BOOM Verilator simulator through
	execute_boom_program_batch when trials are independent; use
	execute_boom_program for a single trial or a trial that depends on prior output.
	Feed validator compiler/simulation evidence back to the generator for bounded
	revisions. Treat the cache report as hardware evidence, not as a vulnerability
	finding. Preserve attempts, distinguish build failures from falsification,
	and finish with the required status and limitations.

Cache report:
{response.result}
"""
    print("Running the Google ADK BOOM exploration coordinator...")
    exploration_text = asyncio.run(run_adk_agent(
        agent_infra.root_agent, exploration_prompt,
        "chiastra_boom_vulnerability_exploration"))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "exploration_report.md").write_text(
        exploration_text, encoding="utf-8")
    (OUTPUT_DIR / "exploration_runs.json").write_text(
        json.dumps(execution_records, indent=2), encoding="utf-8")
    print(f"Exploration report written to "
          f"{(OUTPUT_DIR / 'exploration_report.md').resolve()}")


if __name__ == "__main__":
    main()
