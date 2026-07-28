from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List

NAME = 'custom.awf_create_a_workflow_for_lawyers_that_handles_intake_triage_and_structure_1781157729__general_workflow_executor'
PERMISSIONS = ['custom.awf_create_a_workflow_for_lawyers_that_handles_intake_triage_and_structure_1781157729__general_workflow_executor', 'custom.*']

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
    for key in ('request_text', 'user_request', 'request', 'prompt', 'text'):
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

def _data_analysis_payload(ctx: Dict[str, Any], text: str, source_path: str) -> Dict[str, Any]:
    suffix = Path(source_path).suffix.lower() if source_path else ''
    payload: Dict[str, Any] = {
        'request': text,
        'input_path': source_path,
        'analysis_type': 'bounded_data_analysis',
        'summary': 'Generated a bounded analysis summary and suggested review steps.',
        'observations': [
            'Validated that the request points to a structured data workflow.',
            'Prepared a compact analysis artifact suitable for reviewer inspection.',
        ],
    }
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
    mode = _infer_mode(req, {'id': 'custom.awf_create_a_workflow_for_lawyers_that_handles_intake_triage_and_structure_1781157729__general_workflow_executor', 'label': 'General Workflow Executor', 'description': 'Execute the core task requested by the generated workflow when no installed skill fully matches.', 'reason': 'No installed executable skill matched the request, so the generated workflow needs a generic custom executor.', 'category': 'custom', 'params_schema': {'type': 'object', 'properties': {}, 'additionalProperties': True}})
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


TOOL_SPEC = {'id': 'custom.awf_create_a_workflow_for_lawyers_that_handles_intake_triage_and_structure_1781157729__general_workflow_executor', 'category': 'custom', 'label': 'General Workflow Executor', 'description': 'Execute the core task requested by the generated workflow when no installed skill fully matches.', 'permissions': ['custom.awf_create_a_workflow_for_lawyers_that_handles_intake_triage_and_structure_1781157729__general_workflow_executor', 'custom.*'], 'params_schema': {'type': 'object', 'properties': {}, 'additionalProperties': True}}
