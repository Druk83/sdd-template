"""Детерминированное извлечение явных высказываний и логических связок."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .ingestion import SourceDocument

_HEADING_RE = re.compile(r'^\s{0,3}(?P<marks>#{1,6})\s+(?P<heading>.+?)\s*#*\s*$')
_LIST_RE = re.compile(r'^\s*(?:[-*+]\s+|\d+[.)]\s+)(?P<text>.+?)\s*$')
_FENCE_RE = re.compile(r'^\s*(?:```|~~~)')
_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+(?=[A-ZА-ЯЁ])')
_LABEL_RE = re.compile(r'^\s*(?P<label>[A-Za-zА-Яа-яЁё_]+)\s*:\s*(?P<text>.+?)\s*$')
_MODAL_RE = re.compile(
    r'\b(?P<marker>должен|должна|должны|следует|необходимо|обязан|обязана|обязаны|'
    r'запрещено|нельзя|не\s+допускается|разрешено|можно|must|shall|should|required|'
    r'prohibited|forbidden|may|allowed)\b',
    re.IGNORECASE,
)
_QUESTION_RE = re.compile(r'(?:\?|^(?:вопрос|question)\s*:)', re.IGNORECASE)
_DEFINITION_RE = re.compile(
    r'^\s*(?!(?:найти|создать|проверить|используй|примени|добавь|удали|сформируй|'
    r'find|create|check|use|apply|add|delete|generate)\b)'
    r'(?P<term>[A-Za-zА-Яа-яЁё][\wА-Яа-яЁё _-]{0,80}?)'
    r'(?:\s*(?:—|-|:)\s*(?:это|означает|называется|определяется\s+как)\s+'
    r'|\s+(?:means|is\s+defined\s+as)\s+)'
    r'(?P<body>.+?)\s*[.!]?$',
    re.IGNORECASE,
)
_CAUSAL_RE = re.compile(r'\b(?:потому что|поэтому|причин|следстви|because|therefore|thus)\b', re.IGNORECASE)
_ARGUMENT_RE = re.compile(r'\b(?:так как|поскольку|следовательно|because|therefore|hence)\b', re.IGNORECASE)
_EXAMPLE_RE = re.compile(r'\b(?:например|пример|for example|e\.g\.)\b', re.IGNORECASE)
_NARRATIVE_RE = re.compile(r'\b(?:сначала|затем|после этого|далее|потом|first|then|after that|next)\b', re.IGNORECASE)
_OPINION_RE = re.compile(r'\b(?:вероятно|предполагается|предполагаем|гипотеза|считается|полагаю|может быть|probably|assume|hypothesis|opinion)\b', re.IGNORECASE)
_FORECAST_RE = re.compile(r'\b(?:ожидается|прогноз|будет|будут|forecast|expected|will)\b', re.IGNORECASE)
_FACT_RE = re.compile(r'^(?:факт|fact|известно|зафиксировано|установлено)\s*:', re.IGNORECASE)
_IMPERATIVE_RE = re.compile(r'^(?:проверить|создать|вернуть|обновить|добавить|удалить|сформировать|зарегистрировать|выполнить|read|create|return|update|add|delete|generate|register)\b', re.IGNORECASE)
_IFF_RE = re.compile(r'\b(?:тогда\s+и\s+только\s+тогда|if\s+and\s+only\s+if)\b', re.IGNORECASE)
_ONLY_IF_RE = re.compile(r'\b(?:только\s+если|only\s+if)\b', re.IGNORECASE)
_IF_RE = re.compile(r'^(?:если|когда|при\s+условии|в\s+случае|if|when)\s+(?P<left>.+?)(?:,\s*то\s+|\s+then\s+)(?P<right>.+)$', re.IGNORECASE)
_CONDITION_PREFIX_RE = re.compile(r'^(?:если|когда|при\s+условии|в\s+случае|if|when)\b', re.IGNORECASE)
_XOR_RE = re.compile(r'\b(?:ровно\s+один|только\s+один\s+из|but\s+not\s+both|exactly\s+one)\b', re.IGNORECASE)
_OR_RE = re.compile(r'\b(?:или|or)\b', re.IGNORECASE)
_AMBIGUOUS_OR_RE = re.compile(r'\bлибо\b', re.IGNORECASE)
_AND_RE = re.compile(r'\b(?:и|and)\b', re.IGNORECASE)
_NOT_RE = re.compile(r'^(?:не|not)\s+', re.IGNORECASE)
_ALL_RE = re.compile(r'^(?:каждый|все|любой|every|all|each)\b', re.IGNORECASE)
_EXISTS_RE = re.compile(r'^(?:хотя\s+бы\s+один|существует|at\s+least\s+one|there\s+is)\b', re.IGNORECASE)
_EXCEPTION_RE = re.compile(r'\b(?:кроме|за\s+исключением|except|unless)\s+(?P<value>[^.;]+)', re.IGNORECASE)
_CONSTRAINT_RE = re.compile(r'\b(?:до|не\s+позднее|в\s+течение|только\s+при|within|before|no\s+later\s+than)\s+(?P<value>[^.;]+)', re.IGNORECASE)
_VIOLATION_RE = re.compile(r'\b(?:при\s+нарушении|если\s+нарушено|in\s+case\s+of\s+violation)\s*(?P<value>[^.;]*)', re.IGNORECASE)
_SANCTION_RE = re.compile(r'\b(?:иначе|санкция|штраф|блокируется|otherwise|sanction|penalty)\s*[:,-]?\s*(?P<value>[^.;]*)', re.IGNORECASE)
_PRIORITY_RE = re.compile(r'\b(?:приоритет|имеет\s+приоритет|priority)\s*[:,-]?\s*(?P<value>[^.;]*)', re.IGNORECASE)
_RESULT_RE = re.compile(r'\b(?:результат|в\s+результате|итог|result)\s*[:,-]?\s*(?P<value>[^.;]*)', re.IGNORECASE)
_SIMPLE_FACT_EXCLUSION_RE = re.compile(
    r'\?|(?:^|\s)(?:вопрос|question)\s*:'
    r'|\b(?:должен|должна|должны|следует|необходимо|обязан|обязана|обязаны|'
    r'запрещено|нельзя|не\s+допускается|разрешено|можно|must|shall|should|required|'
    r'prohibited|forbidden|may|allowed|например|пример|for\s+example|e\.g\.|'
    r'это|означает|называется|определяется\s+как|is\s+defined\s+as|means|так\s+как|'
    r'поскольку|следовательно|because|therefore|hence|потому\s+что|поэтому|причин|'
    r'следстви|вероятно|предполагается|предполагаем|гипотез|считается|полагаю|может\s+быть|'
    r'probably|assume|hypothesis|opinion|ожидается|прогноз|будет|будут|forecast|expected|will|'
    r'сначала|затем|после\s+этого|далее|потом|first|then|after\s+that|next|'
    r'проверить|создать|вернуть|обновить|добавить|удалить|сформировать|зарегистрировать|'
    r'выполнить|read|create|return|update|add|delete|generate|register|'
    r'тогда\s+и\s+только\s+тогда|if\s+and\s+only\s+if|только\s+если|only\s+if|'
    r'если|когда|при\s+условии|в\s+случае|if|when|ровно\s+один|только\s+один\s+из|'
    r'but\s+not\s+both|exactly\s+one|или|либо|\bor\b|^(?:не|not)\s+|'
    r'каждый|все|любой|every|all|each|хотя\s+бы\s+один|существует|at\s+least\s+one|there\s+is|'
    r'одновременно|both)\b',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StructuralAnalysis:
    propositions: list[dict]
    logical_expressions: list[dict]
    recognized_lines: frozenset[int]


class _Analyzer:
    def __init__(self, document: SourceDocument, document_index: int) -> None:
        self.document = document
        self.document_index = document_index
        self.expression_index = 0
        self.proposition_index = 0
        self.expressions: list[dict] = []
        self.is_normative_manifest = '.manifest' in {part.casefold() for part in self.document.path.parts}

    def _ref(self, line: int, fragment: str, section_path: list[str]) -> dict:
        ref = {
            'relative_path': self.document.relative_path,
            'line_range': {'start': line, 'end': line},
            'fragment': fragment,
        }
        if section_path:
            ref['section_path'] = list(section_path)
        return ref

    def _role(self, text: str | None, line: int, section_path: list[str]) -> dict | None:
        if text is None:
            return None
        value = text.strip(' ,;:.')
        if not value:
            return None
        ref = self._ref(line, value, section_path)
        return {'text': value, 'source_ref': ref, 'evidence': [ref]}

    def _atom(self, text: str, line: int, section_path: list[str]) -> dict:
        value = text.strip(' ,;:.')
        ref = self._ref(line, value, section_path)
        return {'kind': 'atom', 'text': value, 'source_ref': ref, 'evidence': [ref]}

    def _expression(
        self,
        operator: str,
        operands: list[dict],
        line: int,
        section_path: list[str],
        connector: str,
        *,
        status: str = 'confirmed',
        alternatives: list[str] | None = None,
    ) -> str:
        self.expression_index += 1
        expression_id = f'logical-expression-{self.document_index:03d}-{self.expression_index:03d}'
        ref = self._ref(line, connector, section_path)
        expression = {
            'id': expression_id,
            'operator': operator,
            'operands': operands,
            'source_ref': ref,
            'evidence': [ref],
            'confidence': 0.5 if status == 'review_required' else 1.0,
            'status': status,
        }
        if alternatives:
            expression['alternatives'] = alternatives
        self.expressions.append(expression)
        return expression_id

    def _operand(self, text: str, line: int, section_path: list[str]) -> dict:
        nested = self._parse_expression(text, line, section_path)
        if nested is not None:
            ref = self._ref(line, text.strip(), section_path)
            return {'kind': 'expression', 'expression_id': nested, 'source_ref': ref, 'evidence': [ref]}
        return self._atom(text, line, section_path)

    @staticmethod
    def _split(text: str, pattern: re.Pattern[str]) -> tuple[str, str] | None:
        match = pattern.search(text)
        if match is None:
            return None
        left = text[:match.start()].strip(' ,;:.')
        right = text[match.end():].strip(' ,;:.')
        if not left or not right:
            return None
        return left, right

    @staticmethod
    def _has_logical_context(text: str) -> bool:
        return bool(re.search(r'\b(?:если|когда|при\s+условии|в\s+случае|both|одновременно|all|все)\b', text, re.IGNORECASE))

    def _parse_expression(self, text: str, line: int, section_path: list[str]) -> str | None:
        value = text.strip(' ,;:.')
        if not value:
            return None
        split = self._split(value, _IFF_RE)
        if split is not None:
            return self._expression('IFF', [self._operand(split[0], line, section_path), self._operand(split[1], line, section_path)], line, section_path, 'тогда и только тогда')
        split = self._split(value, _ONLY_IF_RE)
        if split is not None:
            return self._expression('IMPLIES', [self._operand(split[0], line, section_path), self._operand(split[1], line, section_path)], line, section_path, 'только если')
        conditional = _IF_RE.match(value)
        if conditional is not None:
            return self._expression('IMPLIES', [self._operand(conditional.group('left'), line, section_path), self._operand(conditional.group('right'), line, section_path)], line, section_path, 'если')
        if _XOR_RE.search(value):
            split = self._split(value, _OR_RE) or self._split(value, _AMBIGUOUS_OR_RE)
            if split is not None:
                return self._expression('XOR', [self._operand(split[0], line, section_path), self._operand(split[1], line, section_path)], line, section_path, 'ровно один')
        split = self._split(value, _OR_RE)
        if split is not None:
            return self._expression('OR', [self._operand(split[0], line, section_path), self._operand(split[1], line, section_path)], line, section_path, 'или')
        split = self._split(value, _AMBIGUOUS_OR_RE)
        if split is not None:
            if self.is_normative_manifest:
                return self._expression('OR', [self._operand(split[0], line, section_path), self._operand(split[1], line, section_path)], line, section_path, 'либо')
            return self._expression('OR', [self._operand(split[0], line, section_path), self._operand(split[1], line, section_path)], line, section_path, 'либо', status='review_required', alternatives=['OR', 'XOR'])
        if self._has_logical_context(value):
            split = self._split(value, _AND_RE)
            if split is not None:
                return self._expression('AND', [self._operand(split[0], line, section_path), self._operand(split[1], line, section_path)], line, section_path, 'и')
        negation = _NOT_RE.match(value)
        if negation is not None:
            return self._expression('NOT', [self._atom(value[negation.end():], line, section_path)], line, section_path, negation.group(0).strip())
        quantifier = _ALL_RE.match(value)
        if quantifier is not None:
            return self._expression('ALL', [self._atom(value, line, section_path)], line, section_path, quantifier.group(0))
        quantifier = _EXISTS_RE.match(value)
        if quantifier is not None:
            return self._expression('EXISTS', [self._atom(value, line, section_path)], line, section_path, quantifier.group(0))
        return None

    @staticmethod
    def _statement_type(text: str) -> tuple[str, float]:
        if _QUESTION_RE.search(text):
            return 'question', 1.0
        modality = _MODAL_RE.search(text)
        if modality is not None:
            if text[modality.end():].strip(' ,;:.'):
                return 'norm', 0.9
            return 'narrative', 0.7
        if _EXAMPLE_RE.search(text):
            return 'example', 0.9
        if _DEFINITION_RE.search(text):
            return 'definition', 0.8
        if _ARGUMENT_RE.search(text):
            return 'argument', 0.75
        if _CAUSAL_RE.search(text):
            return 'causal', 0.75
        if _OPINION_RE.search(text):
            return 'opinion_or_hypothesis', 0.75
        if _FORECAST_RE.search(text):
            return 'forecast', 0.7
        if _NARRATIVE_RE.search(text):
            return 'narrative', 0.75
        if _IF_RE.match(text.strip(' ,;:.')):
            return 'causal', 0.75
        if _CONDITION_PREFIX_RE.match(text.strip()):
            return 'unclassified', 0.5
        if _IMPERATIVE_RE.search(text):
            return 'unclassified', 0.5
        if _FACT_RE.search(text) or (len(text.split()) >= 2 and text.rstrip().endswith(('.', '!'))):
            return 'fact', 0.65
        return 'unclassified', 0.5

    @staticmethod
    def _is_simple_fact(text: str) -> bool:
        """Возвращает True только для нейтрального повествовательного факта."""
        value = text.strip()
        return (
            len(value.split()) >= 2
            and value.endswith(('.', '!'))
            and _SIMPLE_FACT_EXCLUSION_RE.search(value) is None
        )

    @staticmethod
    def _modality(text: str) -> str | None:
        match = _MODAL_RE.search(text)
        if match is None:
            return None
        marker = match.group('marker').casefold().replace('ё', 'е')
        if marker in {'запрещено', 'нельзя', 'не допускается', 'prohibited', 'forbidden'}:
            return 'PROHIBITION'
        if marker in {'разрешено', 'можно', 'may', 'allowed'}:
            return 'PERMISSION'
        return 'OBLIGATION'

    @staticmethod
    def _conditional_body(text: str) -> str:
        match = _IF_RE.match(text.strip(' ,;:.'))
        return match.group('right') if match is not None else text

    def _norm_roles(self, text: str, line: int, section_path: list[str], expression_id: str | None) -> dict:
        body = self._conditional_body(text)
        modality_match = _MODAL_RE.search(body)
        subject = None
        predicate = None
        obj = None
        if modality_match is not None:
            before = body[:modality_match.start()].strip(' ,;:.')
            subject = self._role(before, line, section_path)
            action = body[modality_match.end():].strip(' ,;:.')
            action = re.split(r'\b(?:кроме|за\s+исключением|иначе|при\s+нарушении|санкция|приоритет)\b', action, maxsplit=1, flags=re.IGNORECASE)[0].strip(' ,;:.')
            action_match = re.match(r'(?P<verb>[A-Za-zА-Яа-яЁё]+(?:ть|ться)?|[A-Za-z]+)\s+(?P<object>.+)$', action)
            if action_match is not None:
                predicate = self._role(action_match.group('verb'), line, section_path)
                obj = self._role(action_match.group('object'), line, section_path)
            else:
                predicate = self._role(action, line, section_path)
        matches = {
            'constraint': _CONSTRAINT_RE.search(text),
            'exception': _EXCEPTION_RE.search(text),
            'violation': _VIOLATION_RE.search(text),
            'sanction': next(reversed(list(_SANCTION_RE.finditer(text))), None),
            'priority': _PRIORITY_RE.search(text),
            'consequence': _RESULT_RE.search(text),
        }
        return {
            'subject': subject,
            'predicate': predicate,
            'object': obj,
            'constraint': self._role(matches['constraint'].group('value') if matches['constraint'] else None, line, section_path),
            'condition': {'expression_id': expression_id} if expression_id is not None and _IF_RE.match(text.strip(' ,;:.')) else None,
            'exceptions': [self._role(matches['exception'].group('value'), line, section_path)] if matches['exception'] else [],
            'consequence': self._role(matches['consequence'].group('value') if matches['consequence'] else None, line, section_path),
            'violation': self._role(matches['violation'].group('value') if matches['violation'] else None, line, section_path),
            'sanction': self._role(matches['sanction'].group('value') if matches['sanction'] else None, line, section_path),
            'priority': self._role(matches['priority'].group('value') if matches['priority'] else None, line, section_path),
        }

    def _proposition(self, text: str, line: int, section_path: list[str]) -> dict | None:
        value = text.strip()
        if not value:
            return None
        simple_fact = self._is_simple_fact(value)
        if simple_fact:
            statement_type, confidence = 'fact', 0.65
            expression_id, expression_status = None, 'confirmed'
        else:
            statement_type, confidence = self._statement_type(value)
            expression_id = self._parse_expression(value, line, section_path)
            expression_status = next(
                (item['status'] for item in reversed(self.expressions) if item['id'] == expression_id),
                'confirmed',
            )
        roles = self._norm_roles(value, line, section_path, expression_id) if statement_type == 'norm' else {
            'subject': None, 'predicate': None if simple_fact else self._role(value, line, section_path), 'object': None,
            'constraint': None, 'condition': None, 'exceptions': [], 'consequence': None,
            'violation': None, 'sanction': None, 'priority': None,
        }
        self.proposition_index += 1
        ref = self._ref(line, value, section_path)
        status = 'review_required' if statement_type == 'unclassified' or expression_status == 'review_required' else 'confirmed'
        return {
            'id': f'proposition-{self.document_index:03d}-{self.proposition_index:03d}',
            'type': statement_type,
            **roles,
            'modality': self._modality(value) if statement_type == 'norm' else None,
            'logical_expression': {'expression_id': expression_id} if expression_id is not None else None,
            'source_ref': ref,
            'evidence': [ref],
            'extraction_method': 'structural_sentence',
            'confidence': 0.5 if status == 'review_required' else confidence,
            'status': status,
        }

    def analyze(self) -> StructuralAnalysis:
        propositions: list[dict] = []
        recognized_lines: set[int] = set()
        section_stack: list[tuple[int, str]] = []
        in_fence = False
        for line_number, source_line in enumerate(self.document.text.splitlines(), start=1):
            if _FENCE_RE.match(source_line):
                in_fence = not in_fence
                continue
            if in_fence or source_line.lstrip().startswith(('|', '>', '<!--', '<')):
                continue
            heading = _HEADING_RE.match(source_line)
            if heading is not None:
                level = len(heading.group('marks'))
                while section_stack and section_stack[-1][0] >= level:
                    section_stack.pop()
                section_stack.append((level, heading.group('heading').strip()))
                continue
            list_match = _LIST_RE.match(source_line)
            text = list_match.group('text') if list_match is not None else source_line.strip()
            if not text or text in {'---', '***', '___'}:
                continue
            label = _LABEL_RE.match(text)
            if label is not None:
                text = label.group('text')
            section_path = [heading for _, heading in section_stack]
            for sentence in _SENTENCE_RE.split(text):
                proposition = self._proposition(sentence, line_number, section_path)
                if proposition is not None and proposition['type'] != 'unclassified':
                    propositions.append(proposition)
                    recognized_lines.add(line_number)
        return StructuralAnalysis(propositions, self.expressions, frozenset(recognized_lines))


def analyze_document(document: SourceDocument, document_index: int) -> StructuralAnalysis:
    """Анализирует Markdown/plain text без внешних знаний и сетевых вызовов."""
    return _Analyzer(document, document_index).analyze()
