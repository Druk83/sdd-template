"""Command-line interface for agent-logic."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import sys
from pathlib import Path

from .agent_adapter import format_agent_result, load_agent_context, run_agent_cycle
from .compilation import compile_model
from .decisions import apply_human_decision, decision_envelope
from .errors import AgentLogicError, OutputError
from .ingestion import load_sources
from .proof_contract import build_proof_result, load_explicit_hypothesis, validate_formal_model
from .proof_engine import evaluate
from .reporting import build_report, output_content
from .runtime_store import RuntimeStore
from .solver_adapter import available_adapters
from .validation import validate_model

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-logic", description="Compile text and Markdown materials into ASIR.")
    commands = parser.add_subparsers(dest="command", required=True)
    compile_parser = commands.add_parser("compile", help="compile one file or a directory")
    compile_parser.add_argument("path", nargs="?", default=".source", help="input file or directory (default: .source)")
    compile_parser.add_argument("--format", choices=("json", "md", "text", "context"), default="json")
    compile_parser.add_argument("--output", help="explicit result path; requires --write")
    compile_parser.add_argument("--write", action="store_true", help="write only the explicitly named new result file")
    compile_parser.add_argument("--replace", action="store_true", help="allow replacing an existing output; requires --write")
    compile_parser.add_argument("--request", help="original user request that initiated the check")
    compile_parser.add_argument("--requested-at", help="request registration time in ISO 8601 supplied by the caller")

    agent_parser = commands.add_parser("agent", help="consume an agent context and build a local execution plan")
    agent_parser.add_argument("context", help="agent_context JSON file or - to read JSON from stdin")
    agent_parser.add_argument("--format", choices=("json", "text"), default="text")
    agent_parser.add_argument("--output", help="explicit result path; requires --write")
    agent_parser.add_argument("--write", action="store_true", help="write only the explicitly named new result file")
    agent_parser.add_argument("--replace", action="store_true", help="allow replacing an existing output; requires --write")
    agent_parser.add_argument("--limit", type=int, default=20, help="maximum number of planned actions (default: 20; 0 means all)")

    prove_parser = commands.add_parser("prove", help="evaluate an explicit formal hypothesis against an ASIR model")
    prove_parser.add_argument("model", help="ASIR model JSON file")
    prove_parser.add_argument("--hypothesis", help="explicit hypothesis JSON file; otherwise an approved model hypothesis is required")
    prove_parser.add_argument("--format", choices=("json", "md", "text", "context"), default="json")
    prove_parser.add_argument("--output", help="explicit result path; requires --write")
    prove_parser.add_argument("--write", action="store_true", help="write only the explicitly named new result file")
    prove_parser.add_argument("--replace", action="store_true", help="allow replacing an existing output; requires --write")
    decision_parser = commands.add_parser('decision', help='show decision cards or apply a human decision')
    decision_parser.add_argument('model', help='ASIR model JSON file')
    decision_parser.add_argument('--response', help='human decision response JSON file')
    decision_parser.add_argument('--format', choices=('json', 'md', 'text', 'context'), default='json')
    decision_parser.add_argument('--output', help='explicit result path; requires --write')
    decision_parser.add_argument('--write', action='store_true', help='write only the explicitly named new result file')
    decision_parser.add_argument('--replace', action='store_true', help='allow replacing an existing output; requires --write')

    solver_parser = commands.add_parser("solver", help="inspect local external-solver contracts without running a provider")
    solver_parser.add_argument("action", choices=("list",), help="available safe action")
    solver_parser.add_argument("--format", choices=("json", "text"), default="text")
    solver_parser.set_defaults(output=None, replace=False, write=False)
    _configure_runtime_commands(commands, compile_parser, decision_parser)
    return parser


def _configure_runtime_commands(commands, compile_parser, decision_parser) -> None:
    compile_parser.add_argument('--store', action='store_true', help='persist the result in the local runtime store')
    compile_parser.add_argument('--workspace', default='.', help='workspace containing .tools/agent-logic/.runtime')
    decision_parser.add_argument('--store', action='store_true', help='persist the result in the local runtime store')
    decision_parser.add_argument('--workspace', default='.', help='workspace containing .tools/agent-logic/.runtime')
    runtime_parser = commands.add_parser('runtime', help='inspect or maintain the local runtime store')
    runtime_commands = runtime_parser.add_subparsers(dest='runtime_command', required=True)
    runtime_list = runtime_commands.add_parser('list', help='list stored model versions without creating a database')
    runtime_list.add_argument('--workspace', default='.', help='workspace containing .tools/agent-logic/.runtime')
    runtime_list.add_argument('--format', choices=('json', 'text'), default='text')
    runtime_cleanup = runtime_commands.add_parser('cleanup', help='remove unlinked intermediate versions')
    runtime_cleanup.add_argument('--workspace', default='.', help='workspace containing .tools/agent-logic/.runtime')
    runtime_cleanup.add_argument('--write', action='store_true', help='apply cleanup; without it only show candidates')
    runtime_cleanup.add_argument('--format', choices=('json', 'text'), default='text')
    runtime_action = runtime_commands.add_parser('action', help='register a completed action for a stored version')
    runtime_action.add_argument('model_version', help='stored ASIR model version')
    runtime_action.add_argument('--initiator', required=True, help='person, agent or plugin that performed the action')
    runtime_action.add_argument('--basis', required=True, help='decision or rule authorizing the action')
    runtime_action.add_argument('--result', required=True, help='registered action result')
    runtime_action.add_argument('--workspace', default='.', help='workspace containing .tools/agent-logic/.runtime')
    runtime_action.add_argument('--write', action='store_true', help='explicitly allow action registration')
    runtime_action.add_argument('--format', choices=('json', 'text'), default='text')
    runtime_parser.set_defaults(output=None, replace=False, write=False)


def _validate_requested_at(value: str | None) -> None:
    """Проверяет переданное агентом время регистрации без его подмены."""
    if value is None:
        return
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise OutputError("--requested-at must use ISO 8601 with a UTC offset") from exc
    if "T" not in value or parsed.tzinfo is None:
        raise OutputError("--requested-at must use ISO 8601 with a UTC offset")


def _write_new(path: str, content: str, *, replace: bool = False) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if replace else "x"
    try:
        with target.open(mode, encoding="utf-8", newline=chr(10)) as stream:
            stream.write(content)
    except FileExistsError as exc:
        raise OutputError(f"refusing to overwrite existing output: {target}; use --replace explicitly") from exc


def _read_json(path: str) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
    except OSError as exc:
        raise OutputError(f'cannot read JSON file: {path}') from exc
    except json.JSONDecodeError as exc:
        raise OutputError(f'invalid JSON file: {path}') from exc
    if not isinstance(value, dict):
        raise OutputError(f'JSON root must be an object: {path}')
    return value

def _format_runtime(value: object, output_format: str) -> str:
    if output_format == 'json':
        return json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if isinstance(value, list):
        return '\n'.join(' '.join(f'{key}={item[key]}' for key in sorted(item)) for item in value) + ('\n' if value else '')
    if isinstance(value, dict):
        return '\n'.join(f'{key}: {value[key]}' for key in sorted(value)) + '\n'
    return str(value) + '\n'

def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    is_decision = args.command == 'decision'
    is_prove = args.command == 'prove'
    is_runtime = args.command == 'runtime'
    is_solver = args.command == 'solver'
    if is_decision or is_runtime or is_prove or is_solver:
        args.command = 'compile'
    if args.command not in {"compile", "agent"}:
        parser.error("unknown command")
    if args.output and not args.write:
        print("agent-logic: --output requires --write", file=sys.stderr)
        return 1
    if args.replace and not args.write:
        print("agent-logic: --replace requires --write", file=sys.stderr)
        return 1
    if args.write and not args.output and not is_runtime:
        print("agent-logic: --write requires an explicit --output path", file=sys.stderr)
        return 1
    if args.command == "agent" and args.limit < 0:
        print("agent-logic: --limit must be non-negative", file=sys.stderr)
        return 1
    try:
        if args.command == "agent":
            context = load_agent_context(args.context)
            result = run_agent_cycle(
                context,
                action_limit=None if args.limit == 0 else args.limit,
            )
            content = format_agent_result(result, args.format)
            if args.write:
                _write_new(args.output, content, replace=args.replace)
            else:
                sys.stdout.write(content)
            if result["status"] == "REVIEW_REQUIRED":
                sys.stderr.write("agent-logic: context requires review before execution\n")
                return 2
            return 0

        if is_solver:
            sys.stdout.write(_format_runtime(available_adapters(), args.format))
            return 0
        if is_runtime:
            store = RuntimeStore(args.workspace)
            if args.runtime_command == 'list':
                result = {'summary': store.summary(), 'versions': store.list_versions()}
            elif args.runtime_command == 'cleanup':
                result = store.cleanup(apply=args.write)
            else:
                if not args.write:
                    raise OutputError('runtime action requires --write')
                result = store.record_action(args.model_version, initiator=args.initiator, basis=args.basis, result=args.result)
            sys.stdout.write(_format_runtime(result, args.format))
            return 0

        if is_prove:
            model = _read_json(args.model)
            sources = model.get("sources", [])
            source_paths = {
                source["relative_path"]
                for source in sources
                if isinstance(source, dict) and isinstance(source.get("relative_path"), str)
            } if isinstance(sources, list) else set()
            if args.hypothesis:
                hypothesis = load_explicit_hypothesis(_read_json(args.hypothesis), source_paths)
            else:
                existing = model.get("hypothesis")
                if not isinstance(existing, dict) or existing.get("formalization_status") != "approved":
                    raise OutputError("prove requires --hypothesis or an approved hypothesis in the ASIR model")
                hypothesis = load_explicit_hypothesis(existing, source_paths)
            proof_model = dict(model)
            proof_model["hypothesis"] = hypothesis
            proof_model["proof_result"] = build_proof_result(model, hypothesis)
            if proof_model["proof_result"]["status"] == "NOT_EVALUATED" and "formal_model" in model:
                artifact_kinds = {
                    profile.get("relative_path"): profile.get("artifact_kind")
                    for profile in model.get("artifact_profiles", [])
                    if isinstance(profile, dict) and isinstance(profile.get("relative_path"), str) and isinstance(profile.get("artifact_kind"), str)
                } if isinstance(model.get("artifact_profiles", []), list) else {}
                source_context: dict[str, dict[str, object]] = {}
                for source in sources:
                    if not isinstance(source, dict):
                        continue
                    relative_path = source.get("relative_path")
                    input_kind = source.get("input_kind")
                    if not isinstance(relative_path, str) or not isinstance(input_kind, str):
                        continue
                    source_context[relative_path] = {
                        "input_kind": input_kind,
                        "artifact_kind": artifact_kinds.get(relative_path),
                    }
                formal_errors = validate_formal_model(model.get("formal_model"), source_context)
                if formal_errors:
                    proof_model["proof_result"]["status"] = "AMBIGUOUS"
                    proof_model["proof_result"]["blocking_reasons"] = [{"code": "INVALID_FORMAL_MODEL", "message": error} for error in formal_errors]
                    proof_model["proof_result"]["explanation"] = {
                        "classification": "AMBIGUOUS",
                        "derivation_traces": [],
                        "alternatives": [],
                        "safe_next_step": {
                            "code": "CLARIFY_FORMALIZATION",
                            "message": "Исправить формальную модель и подтвердить формализацию; новые основания не добавлять.",
                        },
                    }
                    proof_model["proof_result"]["explanation_basis"] = ["explicit_hypothesis", "formal_model_validation"]
                else:
                    proof_model["proof_result"] = evaluate(model, hypothesis)
            report = build_report(proof_model, validate_model(proof_model), input_path=args.model)
            content = output_content(report, args.format)
            if args.write:
                _write_new(args.output, content, replace=args.replace)
            else:
                sys.stdout.write(content)
            if report["exit_code"] == 2:
                sys.stderr.write(report["text_diagnostics"])
            return report["exit_code"]
        if is_decision:
            model = _read_json(args.model)
            if args.response:
                model = apply_human_decision(model, _read_json(args.response))
                report = build_report(model, validate_model(model))
                content = output_content(report, args.format)
                exit_code = report['exit_code']
            elif args.format == 'json':
                content = json.dumps(decision_envelope(model), ensure_ascii=False, indent=2) + '\n'
                exit_code = 0
            else:
                report = build_report(model, validate_model(model))
                content = output_content(report, args.format)
                exit_code = report['exit_code']
            if args.store:
                RuntimeStore(args.workspace).record_report(model, build_report(model, validate_model(model)))
            if args.write:
                _write_new(args.output, content, replace=args.replace)
            else:
                sys.stdout.write(content)
            return exit_code

        _validate_requested_at(args.requested_at)
        input_materials = load_sources(args.path)
        model = compile_model(input_materials.compilation_id, list(input_materials.sources))
        issues = validate_model(model)
        report = build_report(model, issues, input_path=args.path, request_text=args.request, requested_at=args.requested_at)
        if args.store:
            RuntimeStore(args.workspace).record_report(model, report)
        content = output_content(report, args.format)
        if args.write:
            _write_new(args.output, content, replace=args.replace)
        else:
            sys.stdout.write(content)
        if report["exit_code"] == 2:
            sys.stderr.write(report["text_diagnostics"])
        return report["exit_code"]
    except AgentLogicError as exc:
        print(f"agent-logic: error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"agent-logic: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
