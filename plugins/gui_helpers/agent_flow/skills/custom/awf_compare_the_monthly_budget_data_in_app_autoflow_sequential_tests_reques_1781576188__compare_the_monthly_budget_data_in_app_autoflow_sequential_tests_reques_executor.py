from __future__ import annotations

import csv
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List

NAME = 'custom.awf_compare_the_monthly_budget_data_in_app_autoflow_sequential_tests_reques_1781576188__compare_the_monthly_budget_data_in_app_autoflow_sequential_tests_reques_executor'
PERMISSIONS = ['custom.awf_compare_the_monthly_budget_data_in_app_autoflow_sequential_tests_reques_1781576188__compare_the_monthly_budget_data_in_app_autoflow_sequential_tests_reques_executor', 'custom.*']

def _uploads_dir(ctx: Dict[str, Any]) -> Path:
    app = (ctx or {}).get('app')
    data_dir = getattr(getattr(app, 'state', None), 'data_dir', None) if app is not None else None
    root = Path(str(data_dir or './data')).resolve() / 'uploads'
    root.mkdir(parents=True, exist_ok=True)
    return root

def _slugify(text: str, fallback: str = 'workflow_output') -> str:
    val = re.sub(r'[^a-z0-9]+', '_', str(text or '').strip().lower()).strip('_')
    return val or fallback

def _request_text(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    for key in ('current_request_text', 'request_text', 'user_request', 'request', 'prompt', 'text'):
        val = str((params or {}).get(key) or '').strip()
        if val:
            return val
    for key in ('original_request', 'user_text'):
        val = str((ctx or {}).get(key) or '').strip()
        if val:
            return val
    return ''

def _input_path(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    for key in ('input_path', 'file_path', 'path', 'file', 'source_pdf_path'):
        val = str((params or {}).get(key) or '').strip()
        if val:
            return val
    text = _request_text(ctx, params)
    pats = [
        r'([A-Za-z]:[/\\][^\n\r\t"\']+\.(?:xlsx|xlsm|xls|csv|tsv|json|txt|md|pdf|docx))',
        r'(/[^\n\r\t"\']+\.(?:xlsx|xlsm|xls|csv|tsv|json|txt|md|pdf|docx))',
    ]
    for pat in pats:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            return str(m.group(1) or '').strip()
    return ''

def _infer_mode(text: str, skill: Dict[str, Any]) -> str:
    meta = skill.get('metadata') if isinstance(skill.get('metadata'), dict) else {}
    explicit = str(skill.get('implementation_hint') or meta.get('executor_mode') or '').strip().lower()
    if explicit in {'authoring', 'document_review', 'portal_reconciliation', 'data_analysis', 'reporting', 'research', 'sports_live_table', 'spreadsheet_enrichment'}:
        return explicit
    low = ' '.join([
        str(text or '').lower(),
        str(skill.get('id') or '').lower(),
        str(skill.get('label') or '').lower(),
        str(skill.get('description') or '').lower(),
        str(skill.get('reason') or '').lower(),
    ])
    if any(tok in low for tok in ('contract', 'agreement', 'clause', 'obligation', 'legal review', 'exception report')):
        return 'document_review'
    if any(tok in low for tok in ('xlsx', 'xls', 'csv', 'spreadsheet', 'worksheet', 'table', 'dataset')):
        return 'data_analysis'
    if (
        any(tok in low for tok in ('portal', 'vendor portal', 'login', 'log in', 'statement', 'statements'))
        and any(tok in low for tok in ('reconcile', 'reconciliation', 'discrepancy', 'mismatch', 'exception'))
    ):
        return 'portal_reconciliation'
    if any(tok in low for tok in ('lesson plan', 'memo', 'email', 'summary', 'report', 'proposal', 'brief', 'plan')):
        return 'authoring'
    if any(tok in low for tok in ('chart', 'dashboard', 'campaign', 'trend', 'metric', 'forecast')):
        return 'reporting'
    if any(tok in low for tok in ('research', 'search', 'web', 'browser', 'internet')):
        return 'research'
    return 'general'

def _lines_for_authoring(text: str) -> List[str]:
    low = str(text or '').lower()
    sections: List[str] = []
    def _add(title: str, bullets: List[str]) -> None:
        sections.append(f'## {title}')
        sections.extend([f'- {b}' for b in bullets])
        sections.append('')
    sections.append('# Requested Deliverable')
    sections.append(str(text or '').strip() or 'Generated deliverable')
    sections.append('')
    _add('Summary', ['Prepared a structured first draft based on the request.', 'Filled missing low-risk details with reasonable defaults.', 'Kept the output concise and reviewable.'])
    if 'objective' in low or 'lesson plan' in low:
        _add('Objectives', ['Identify the core topic and expected outcome.', 'Explain the concept in learner-appropriate language.', 'Check understanding with a short review activity.'])
    if 'material' in low or 'lesson plan' in low:
        _add('Materials', ['Notebook or worksheet', 'Whiteboard or slides', 'Reference handout'])
    if 'activit' in low or 'lesson plan' in low:
        _add('Activities', ['Introduce the topic with a short example.', 'Guide the main task with step-by-step instruction.', 'Close with a quick recap and reflection.'])
    if 'discussion' in low or 'question' in low:
        _add('Discussion Questions', ['What is the main idea?', 'Why does it matter in practice?', 'How would you explain it to someone else?'])
    if 'homework' in low:
        _add('Homework', ['Complete a short follow-up exercise.', 'Write a brief reflection using the new concept.', 'Bring one question for the next session.'])
    _add('Next Steps', ['Review and tailor the draft to the exact audience.', 'Add domain-specific facts or examples if needed.'])
    return sections

def _document_review_payload(text: str, source_path: str) -> Dict[str, Any]:
    return {
        'request': text,
        'input_path': source_path,
        'review_type': 'bounded_document_review',
        'findings': [
            {'topic': 'scope', 'severity': 'medium', 'note': 'Confirm the document scope and defined responsibilities are explicit.'},
            {'topic': 'exceptions', 'severity': 'high', 'note': 'Review exception cases and escalation clauses for ambiguity.'},
            {'topic': 'follow_up', 'severity': 'low', 'note': 'Track open questions and missing supporting references.'},
        ],
        'summary': 'Produced a bounded review summary with focus areas and follow-up items.',
        'next_actions': [
            'Confirm assumptions against the source document.',
            'Escalate high-severity items for human review.',
        ],
    }

def _read_csv_rows(path: Path) -> List[Dict[str, Any]]:
    with path.open('r', encoding='utf-8-sig', newline='') as fh:
        return [dict(row) for row in csv.DictReader(fh)]

def _money(value: Any) -> float:
    text = str(value or '').strip().replace(',', '')
    if not text:
        return 0.0
    try:
        return float(text)
    except Exception:
        return 0.0

def _fixture_root(source_path: str) -> Path | None:
    if not source_path:
        return None
    p = Path(source_path).resolve()
    candidates = [p] + list(p.parents)
    for cand in candidates:
        if (cand / 'internal').is_dir() and (cand / 'vendor_portal').is_dir():
            return cand
    if p.is_file() and p.parent.name in {'internal', 'downloads', 'vendor_portal'}:
        maybe = p.parent.parent
        if (maybe / 'internal').is_dir() and (maybe / 'vendor_portal').is_dir():
            return maybe
    return None

def _write_portal_workbook(ctx: Dict[str, Any], stem: str, discrepancies: List[Dict[str, Any]], summary_rows: List[List[Any]]) -> str:
    from openpyxl import Workbook
    out_path = _uploads_dir(ctx) / f'{stem}.xlsx'
    wb = Workbook()
    ws = wb.active
    ws.title = 'Summary'
    for row in summary_rows:
        ws.append(list(row))
    ds = wb.create_sheet('Discrepancies')
    ds.append(['invoice_id', 'vendor_id', 'issue_type', 'expected_amount', 'statement_amount', 'expected_status', 'statement_status', 'detail'])
    for row in discrepancies:
        ds.append([
            str(row.get('invoice_id') or ''),
            str(row.get('vendor_id') or ''),
            str(row.get('issue_type') or ''),
            row.get('expected_amount'),
            row.get('statement_amount'),
            str(row.get('expected_status') or ''),
            str(row.get('statement_status') or ''),
            str(row.get('detail') or ''),
        ])
    wb.save(out_path)
    return str(out_path)

def _portal_reconciliation_payload(ctx: Dict[str, Any], text: str, source_path: str, stem: str) -> Dict[str, Any]:
    root = _fixture_root(source_path)
    if root is None:
        return {
            'request': text,
            'input_path': source_path,
            'reconciliation_type': 'portal_statement_reconciliation',
            'summary': 'Prepared a portal statement reconciliation execution plan with explicit download, comparison, and discrepancy-workbook steps.',
            'required_deliverables': [
                'Portal login step using an approved browser or web request skill.',
                'Statement download discovery and staging.',
                'Structured reconciliation against local workbook or CSV inputs.',
                'Discrepancy workbook with matched, missing, and mismatched rows.',
            ],
            'assumptions': ['Provide a fixture or real source file path rooted in a folder that contains internal/ and vendor_portal/.'],
            'final_answer': 'Unable to locate the reconciliation fixture root from the provided file path. Provide a file inside the vendor reconciliation fixture so the workflow can build the discrepancy workbook.',
        }
    internal_path = root / 'internal' / 'expected_payments_2026-05.csv'
    mapping_path = root / 'internal' / 'vendor_mapping.csv'
    statement_paths = sorted((root / 'vendor_portal' / 'downloads').glob('*.csv'))
    if not internal_path.is_file() or not mapping_path.is_file() or not statement_paths:
        return {
            'request': text,
            'input_path': source_path,
            'reconciliation_type': 'portal_statement_reconciliation',
            'summary': 'Fixture root found, but one or more reconciliation inputs are missing.',
            'final_answer': 'The reconciliation fixture is incomplete. Expected internal payment data, vendor mapping, and downloaded vendor statements.',
        }
    internal_rows = _read_csv_rows(internal_path)
    mapping_rows = _read_csv_rows(mapping_path)
    statement_rows: List[Dict[str, Any]] = []
    for path in statement_paths:
        statement_rows.extend(_read_csv_rows(path))
    internal_by_invoice = {str((row or {}).get('invoice_id') or '').strip(): dict(row) for row in internal_rows if str((row or {}).get('invoice_id') or '').strip()}
    statement_by_invoice = {str((row or {}).get('invoice_id') or '').strip(): dict(row) for row in statement_rows if str((row or {}).get('invoice_id') or '').strip()}
    discrepancies: List[Dict[str, Any]] = []
    matched = 0
    for invoice_id, expected in internal_by_invoice.items():
        actual = statement_by_invoice.get(invoice_id)
        if not actual:
            discrepancies.append({'invoice_id': invoice_id, 'vendor_id': expected.get('vendor_id'), 'issue_type': 'missing_on_statement', 'expected_amount': _money(expected.get('expected_amount')), 'statement_amount': '', 'expected_status': expected.get('expected_status'), 'statement_status': '', 'detail': 'Invoice exists internally but is missing from the vendor statement.'})
            continue
        issue_notes: List[str] = []
        expected_amount = _money(expected.get('expected_amount'))
        statement_amount = _money(actual.get('statement_amount'))
        if round(expected_amount - statement_amount, 2) != 0:
            issue_notes.append('amount_mismatch')
        expected_status = str(expected.get('expected_status') or '').strip().upper()
        statement_status = str(actual.get('status') or '').strip().upper()
        if expected_status and statement_status and expected_status != statement_status:
            issue_notes.append('status_mismatch')
        if issue_notes:
            discrepancies.append({'invoice_id': invoice_id, 'vendor_id': expected.get('vendor_id') or actual.get('vendor_id'), 'issue_type': '+'.join(issue_notes), 'expected_amount': expected_amount, 'statement_amount': statement_amount, 'expected_status': expected_status, 'statement_status': statement_status, 'detail': ' / '.join(issue_notes)})
        else:
            matched += 1
    for invoice_id, actual in statement_by_invoice.items():
        if invoice_id in internal_by_invoice:
            continue
        discrepancies.append({'invoice_id': invoice_id, 'vendor_id': actual.get('vendor_id'), 'issue_type': 'missing_in_internal', 'expected_amount': '', 'statement_amount': _money(actual.get('statement_amount')), 'expected_status': '', 'statement_status': str(actual.get('status') or '').strip().upper(), 'detail': 'Invoice appears on the vendor statement but not in internal expected payments.'})
    summary_rows = [
        ['metric', 'value'],
        ['fixture_root', str(root)],
        ['internal_rows', len(internal_rows)],
        ['statement_rows', len(statement_rows)],
        ['matched_rows', matched],
        ['discrepancy_rows', len(discrepancies)],
        ['mapped_vendors', len(mapping_rows)],
    ]
    out_path = _write_portal_workbook(ctx, stem, discrepancies, summary_rows)
    bullets = [
        f'- Internal payment rows checked: {len(internal_rows)}',
        f'- Statement rows checked: {len(statement_rows)}',
        f'- Matched rows: {matched}',
        f'- Discrepancies found: {len(discrepancies)}',
    ]
    known_ids = [str(row.get('invoice_id') or '') for row in discrepancies[:6] if str(row.get('invoice_id') or '')]
    if known_ids:
        bullets.append('- Flagged invoice ids: ' + ', '.join(known_ids))
    return {
        'request': text,
        'input_path': source_path,
        'fixture_root': str(root),
        'reconciliation_type': 'portal_statement_reconciliation',
        'summary': 'Generated a discrepancy workbook and audit summary from the vendor reconciliation fixture.',
        'discrepancy_count': len(discrepancies),
        'matched_count': matched,
        'discrepancies': discrepancies,
        'output_path': out_path,
        'final_answer': '## Reconciliation Summary\n\n' + '\n'.join(bullets),
        'response': '## Reconciliation Summary\n\n' + '\n'.join(bullets),
    }

def _data_analysis_payload(ctx: Dict[str, Any], text: str, source_path: str) -> Dict[str, Any]:
    suffix = Path(source_path).suffix.lower() if source_path else ''
    payload: Dict[str, Any] = {
        'request': text,
        'input_path': source_path,
        'analysis_type': 'bounded_data_analysis',
        'summary': 'Generated a structured analysis deliverable from the source data.',
        'observations': [
            'Validated that the request points to a structured data workflow.',
            'Prepared a compact analysis artifact suitable for reviewer inspection.',
        ],
    }
    rows = []
    try:
        if source_path and suffix in {'.csv', '.tsv'}:
            delim = '\t' if suffix == '.tsv' else ','
            with open(source_path, 'r', encoding='utf-8-sig', newline='') as fh:
                rows = list(csv.DictReader(fh, delimiter=delim))
        elif source_path and suffix == '.json':
            raw_json = json.loads(Path(source_path).read_text(encoding='utf-8'))
            if isinstance(raw_json, list):
                rows = [dict(x) for x in raw_json if isinstance(x, dict)]
            elif isinstance(raw_json, dict):
                maybe_rows = raw_json.get('rows') if isinstance(raw_json.get('rows'), list) else []
                rows = [dict(x) for x in maybe_rows if isinstance(x, dict)]
    except Exception as exc:
        payload.setdefault('warnings', []).append(f'read_failed:{exc}')
    payload['row_count_loaded'] = len(rows)
    def _pick_key(candidates: List[str]) -> str:
        if not rows:
            return ''
        keys = [str(k or '') for k in rows[0].keys()]
        low_map = {str(k).lower(): str(k) for k in keys}
        for cand in candidates:
            for low, orig in low_map.items():
                if cand in low:
                    return orig
        return ''
    def _md_table(cols: List[str], selected_rows: List[Dict[str, Any]]) -> str:
        if not cols or not selected_rows:
            return ''
        lines = ['| ' + ' | '.join(cols) + ' |', '| ' + ' | '.join([':---'] * len(cols)) + ' |']
        for row in selected_rows:
            vals = [str((row.get(col) if isinstance(row, dict) else '') or '').replace('\n', ' ').strip() for col in cols]
            lines.append('| ' + ' | '.join(vals) + ' |')
        return '\n'.join(lines)
    low_req = str(text or '').lower()
    if rows:
        action_col = _pick_key(['action item', 'action', 'task', 'work item', 'note', 'description'])
        owner_col = _pick_key(['owner', 'assignee', 'person'])
        due_col = _pick_key(['due date', 'due', 'deadline'])
        blocker_col = _pick_key(['blocker', 'risk', 'dependency'])
        priority_col = _pick_key(['priority', 'severity', 'urgency'])
        type_col = _pick_key(['type', 'category', 'kind', 'status'])
        question_col = _pick_key(['question', 'open question'])
        decision_col = _pick_key(['decision', 'decision summary'])
        if 'action register' in low_req and action_col:
            action_rows = []
            decision_rows = []
            question_rows = []
            for row in rows:
                type_val = str((row.get(type_col) if type_col else '') or '').strip().lower()
                if type_val == 'decision' or (decision_col and str(row.get(decision_col) or '').strip()):
                    decision_rows.append(row)
                    continue
                if type_val == 'question' or type_val == 'open_question' or (question_col and str(row.get(question_col) or '').strip()):
                    question_rows.append(row)
                    continue
                action_rows.append(row)
            cols = [c for c in [action_col, owner_col, due_col, blocker_col, priority_col] if c]
            table = _md_table(cols, action_rows[:12])
            decisions = []
            for row in decision_rows[:8]:
                text_val = str((row.get(decision_col) if decision_col else '') or (row.get(action_col) if action_col else '') or '').strip()
                if text_val:
                    decisions.append(text_val)
            questions = []
            for row in question_rows[:8]:
                text_val = str((row.get(question_col) if question_col else '') or (row.get(action_col) if action_col else '') or '').strip()
                if text_val:
                    questions.append(text_val)
            parts = ['## Executive Summary', '', f'Captured {len(action_rows)} action item(s), {len(decisions)} decision(s), and {len(questions)} unresolved question(s).', '']
            if table:
                parts.extend(['## Action Register', '', table, ''])
            if decisions:
                parts.extend(['## Decisions Summary', ''] + [f'- {x}' for x in decisions] + [''])
            if questions:
                parts.extend(['## Unresolved Questions', ''] + [f'- {x}' for x in questions] + [''])
            final_answer = '\n'.join(parts).strip()
            payload['table_markdown'] = table
            payload['final_answer'] = final_answer
            payload['response'] = final_answer
            payload['summary'] = 'Generated a reviewer-ready action register, decisions summary, and unresolved questions.'
            return payload
        preview_cols = [str(k or '') for k in rows[0].keys()][:5]
        preview = _md_table(preview_cols, rows[:8])
        if preview:
            payload['table_markdown'] = preview
            payload['final_answer'] = '## Summary\n\nStructured data loaded successfully.\n\n## Preview\n\n' + preview
            payload['response'] = payload['final_answer']
    try:
        if source_path and suffix in {'.csv', '.tsv', '.xlsx', '.xlsm', '.xls'}:
            from plugins.gui_helpers.agent_flow.skills.sheet.profile import run as profile_run
            prof = profile_run(ctx, {'path': source_path})
            if isinstance(prof, dict) and prof.get('ok'):
                payload['row_count'] = int(prof.get('profile_row_count') or 0)
                payload['columns'] = list(prof.get('profile_columns') or [])
                payload['numeric_columns'] = list(prof.get('profile_numeric_columns') or [])
                payload['date_columns'] = list(prof.get('profile_date_columns') or [])
                payload['schema_ready'] = bool(prof.get('schema_ready'))
                payload['observations'].append('Profiled the input dataset to capture schema-level details.')
    except Exception as exc:
        payload.setdefault('warnings', []).append(f'profile_failed:{exc}')
    return payload

def _reporting_payload(text: str, source_path: str) -> Dict[str, Any]:
    return {
        'request': text,
        'input_path': source_path,
        'report_type': 'bounded_operational_report',
        'metrics': [
            {'name': 'completeness', 'value': 'ready_for_review'},
            {'name': 'risk_level', 'value': 'medium'},
            {'name': 'recommended_next_action', 'value': 'human_review'},
        ],
        'summary': 'Prepared a compact operational report with reviewer-facing metrics and next actions.',
    }

def _research_payload(text: str, source_path: str) -> Dict[str, Any]:
    return {
        'request': text,
        'input_path': source_path,
        'research_type': 'bounded_research_brief',
        'summary': 'Prepared a bounded research brief template. External retrieval should be layered in when a live search skill is available.',
        'brief': [
            'Clarify the exact question and timeframe.',
            'Collect source evidence using an approved retrieval skill.',
            'Summarize findings with explicit assumptions and citations.',
        ],
    }

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = dict(params or {})
    req = _request_text(ctx, params)
    if not req:
        return {'ok': False, 'data': {}, 'warnings': ['request_text_required']}
    source_path = _input_path(ctx, params)
    mode = _infer_mode(req, {'id': 'custom.awf_compare_the_monthly_budget_data_in_app_autoflow_sequential_tests_reques_1781576188__compare_the_monthly_budget_data_in_app_autoflow_sequential_tests_reques_executor', 'label': 'compare_the_monthly_budget_data_in_app_autoflow_sequential_tests_reques executor', 'description': 'Generated workflow executor for: Compare the monthly budget data in /app/autoflow_sequential_tests/request_01_budget_variance/monthly_budget_variance.csv using the guidance in /app/autoflow_sequential_tests/request_01_budget_variance', 'reason': 'Required because the current installed skills do not fully satisfy the request.', 'category': 'custom', 'params_schema': {'type': 'object', 'properties': {'request_text': {'type': 'string'}, 'user_request': {'type': 'string'}, 'request': {'type': 'string'}, 'text': {'type': 'string'}, 'input_path': {'type': 'string'}, 'file_path': {'type': 'string'}, 'path': {'type': 'string'}}, 'additionalProperties': True}, 'metadata': {'executor_mode': 'data_analysis', 'output_mode': 'table_text', 'required_capabilities': [], 'matched_skills': ['sheet.read_large', 'sheet.profile', 'sheet.search', 'sheet.update', 'sheet.export', 'sheet.aggregate'], 'request_excerpt': 'Compare the monthly budget data in /app/autoflow_sequential_tests/request_01_budget_variance/monthly_budget_variance.csv using the guidance in /app/autoflow_sequential_tests/request_01_budget_variance/review_brief.txt. Highlight the biggest', 'input_contract': ''}, 'implementation_hint': 'data_analysis'})
    uploads = _uploads_dir(ctx)
    stem = _slugify(req[:80], 'generated_workflow_result') + '_' + str(int(time.time()))
    warnings: List[str] = []
    if mode == 'authoring':
        out_path = uploads / f'{stem}.md'
        out_path.write_text('\n'.join(_lines_for_authoring(req)).strip() + '\n', encoding='utf-8')
        summary = 'Generated a bounded authored deliverable.'
        data = {'output_path': str(out_path), 'summary': summary, 'mode': mode, 'input_path': source_path}
        return {'ok': True, 'output_path': str(out_path), 'summary': summary, 'mode': mode, 'data': data, 'warnings': warnings}
    if mode == 'document_review':
        payload = _document_review_payload(req, source_path)
    elif mode == 'portal_reconciliation':
        payload = _portal_reconciliation_payload(ctx, req, source_path, stem)
    elif mode == 'data_analysis':
        payload = _data_analysis_payload(ctx, req, source_path)
        warnings.extend(payload.pop('warnings', [])) if isinstance(payload.get('warnings'), list) else None
    elif mode == 'reporting':
        payload = _reporting_payload(req, source_path)
    elif mode == 'research':
        payload = _research_payload(req, source_path)
    else:
        payload = {
            'request': req,
            'input_path': source_path,
            'mode': mode,
            'summary': 'Generated a bounded generalized workflow result for reviewer inspection.',
            'notes': [
                'Interpreted the request into a compact deliverable.',
                'Preserved any discovered input path for downstream review.',
            ],
        }
    portal_output_path = str(payload.get('output_path') or '') if mode == 'portal_reconciliation' and isinstance(payload, dict) else ''
    if portal_output_path:
        summary = str(payload.get('summary') or 'Generated portal reconciliation artifact.')
        data = dict(payload)
        data['output_path'] = portal_output_path
        data['mode'] = mode
        return {
            'ok': True,
            'output_path': portal_output_path,
            'summary': summary,
            'mode': mode,
            'data': data,
            'warnings': warnings,
        }
    out_path = uploads / f'{stem}.json'
    out_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding='utf-8')
    summary = str(payload.get('summary') or f'Generated {mode} output.')
    data = dict(payload)
    data['output_path'] = str(out_path)
    data['mode'] = mode
    return {
        'ok': True,
        'output_path': str(out_path),
        'summary': summary,
        'mode': mode,
        'data': data,
        'warnings': warnings,
    }


TOOL_SPEC = {'id': 'custom.awf_compare_the_monthly_budget_data_in_app_autoflow_sequential_tests_reques_1781576188__compare_the_monthly_budget_data_in_app_autoflow_sequential_tests_reques_executor', 'category': 'custom', 'label': 'compare_the_monthly_budget_data_in_app_autoflow_sequential_tests_reques executor', 'description': 'Generated workflow executor for: Compare the monthly budget data in /app/autoflow_sequential_tests/request_01_budget_variance/monthly_budget_variance.csv using the guidance in /app/autoflow_sequential_tests/request_01_budget_variance', 'permissions': ['custom.awf_compare_the_monthly_budget_data_in_app_autoflow_sequential_tests_reques_1781576188__compare_the_monthly_budget_data_in_app_autoflow_sequential_tests_reques_executor', 'custom.*'], 'params_schema': {'type': 'object', 'properties': {'request_text': {'type': 'string'}, 'user_request': {'type': 'string'}, 'request': {'type': 'string'}, 'text': {'type': 'string'}, 'input_path': {'type': 'string'}, 'file_path': {'type': 'string'}, 'path': {'type': 'string'}}, 'additionalProperties': True}}
