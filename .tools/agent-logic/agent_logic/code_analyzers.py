'''Pluggable source-code analyzers that produce universal ASIR contributions.'''
from __future__ import annotations

import ast
from typing import Protocol
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CodeAnalysis:
    language: str
    elements: tuple[dict, ...]
    gaps: tuple[dict, ...]


class CodeAnalyzer(Protocol):
    language: str
    suffixes: frozenset[str]

    def analyze(self, path: Path, relative_path: str, text: str) -> CodeAnalysis: ...


class AnalyzerRegistry:
    def __init__(self) -> None:
        self._by_suffix: dict[str, CodeAnalyzer] = {}

    def register(self, analyzer: CodeAnalyzer) -> None:
        for suffix in analyzer.suffixes:
            self._by_suffix[suffix.casefold()] = analyzer

    def analyzer_for(self, suffix: str) -> CodeAnalyzer | None:
        return self._by_suffix.get(suffix.casefold())

    def analyze(self, path: Path, relative_path: str, text: str) -> CodeAnalysis:
        analyzer = self.analyzer_for(path.suffix)
        if analyzer is None:
            return CodeAnalysis('unknown', (), ({'line': 1, 'text': f'Unsupported source language: {path.suffix or "<none>"}', 'fragment': text},))
        return analyzer.analyze(path, relative_path, text)


class PythonAstAnalyzer:
    language = 'python'
    suffixes = frozenset({'.py'})

    def analyze(self, path: Path, relative_path: str, text: str) -> CodeAnalysis:
        try:
            tree = ast.parse(text, filename=relative_path)
        except SyntaxError as exc:
            line = exc.lineno or 1
            return CodeAnalysis('python', (), ({'line': line, 'text': f'Python syntax error: {exc.msg}', 'fragment': exc.text or ''},))
        elements: list[dict] = [
            {'kind': 'entities', 'text': f'module {relative_path}', 'line': 1, 'fragment': relative_path, 'code_kind': 'module'},
        ]
        seen_references: set[tuple[str, int]] = set()
        for node in ast.walk(tree):
            line = getattr(node, 'lineno', 1)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                prefix = 'class' if isinstance(node, ast.ClassDef) else 'function'
                elements.append({'kind': 'entities', 'text': f'{prefix} {node.name}', 'line': line, 'fragment': node.name, 'code_kind': 'declaration'})
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    names = ', '.join(alias.name for alias in node.names)
                else:
                    names = f'{node.module or ""}.{", ".join(alias.name for alias in node.names)}'.strip('.')
                elements.append({'kind': 'dependencies', 'text': f'import {names}', 'line': line, 'fragment': names, 'code_kind': 'import'})
            elif isinstance(node, ast.Call):
                name = ast.unparse(node.func)
                elements.append({'kind': 'actions', 'text': f'call {name}', 'line': line, 'fragment': name, 'code_kind': 'call'})
            elif isinstance(node, (ast.If, ast.While, ast.IfExp)):
                test = ast.unparse(node.test)
                elements.append({'kind': 'conditions', 'text': f'condition {test}', 'line': line, 'fragment': test, 'code_kind': 'branch'})
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                reference = (node.id, line)
                if reference not in seen_references:
                    seen_references.add(reference)
                    elements.append({'kind': 'facts', 'text': f'reference {node.id}', 'line': line, 'fragment': node.id, 'code_kind': 'reference'})
        elements.sort(key=lambda item: (item['line'], item['kind'], item['text']))
        return CodeAnalysis('python', tuple(elements), ())


DEFAULT_ANALYZERS = AnalyzerRegistry()
DEFAULT_ANALYZERS.register(PythonAstAnalyzer())
CODE_LIKE_SUFFIXES = frozenset({'.py', '.js', '.ts', '.tsx', '.java', '.cs', '.go', '.rs', '.c', '.h', '.cpp'})