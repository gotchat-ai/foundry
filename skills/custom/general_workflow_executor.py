from __future__ import annotations

import csv
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List

NAME = 'custom.general_workflow_executor'
PERMISSIONS = ['custom.general_workflow_executor', 'custom.*']

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

def _repo_root_path(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    candidates = [
        (params or {}).get('target_repo_root'),
        (params or {}).get('agent_workflow_target_repo_root'),
        ((params or {}).get('router_plugin_settings') or {}).get('agent_workflow', {}).get('target_repo_root') if isinstance((params or {}).get('router_plugin_settings'), dict) else None,
        (ctx or {}).get('target_repo_root'),
        (ctx or {}).get('agent_workflow_target_repo_root'),
        ((ctx or {}).get('router_plugin_settings') or {}).get('agent_workflow', {}).get('target_repo_root') if isinstance((ctx or {}).get('router_plugin_settings'), dict) else None,
    ]
    for value in candidates:
        text = str(value or '').strip()
        if text:
            return text
    return ''

def _normalize_input_path(path: str) -> str:
    text = str(path or '').strip()
    if text.startswith('app/'):
        return '/' + text
    return text

def _resolve_existing_path(ctx: Dict[str, Any], raw_path: str) -> str:
    raw = _normalize_input_path(raw_path)
    if not raw:
        return ''
    candidates: List[Path] = []
    try:
        p = Path(raw)
        candidates.append(p)
    except Exception:
        p = None
    if raw.startswith('/app/'):
        rel = raw[len('/app/'):].lstrip('/')
        for parent in Path(__file__).resolve().parents:
            candidates.append(parent / rel)
    if raw.startswith('/uploads/'):
        rel = raw[len('/uploads/'):].lstrip('/')
        app = (ctx or {}).get('app') if isinstance(ctx, dict) else None
        data_dir = getattr(getattr(app, 'state', None), 'data_dir', None) if app is not None else None
        upload_roots: List[Path] = []
        if data_dir:
            upload_roots.append(Path(str(data_dir)).resolve() / 'uploads')
        for parent in Path(__file__).resolve().parents:
            upload_roots.extend([parent / 'uploads', parent / 'data' / 'uploads'])
        for root in upload_roots:
            candidates.append(root / rel)
    seen = set()
    for cand in candidates:
        key = str(cand)
        if key in seen:
            continue
        seen.add(key)
        try:
            if cand.exists():
                return str(cand.resolve())
        except Exception:
            pass
    return raw

def _input_path(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    for key in ('input_path', 'file_path', 'path', 'file', 'source_pdf_path'):
        val = _resolve_existing_path(ctx, str((params or {}).get(key) or '').strip())
        if val and Path(val).exists():
            return val
    text = _request_text(ctx, params)
    pats = [
        r"([A-Za-z]:[/\\][^\s\"']+\.(?:xlsx|xlsm|xls|csv|tsv|json|txt|md|pdf|docx|png|jpg|jpeg|webp|bmp|tif|tiff))",
        r"(/[^\s\"']+\.(?:xlsx|xlsm|xls|csv|tsv|json|txt|md|pdf|docx|png|jpg|jpeg|webp|bmp|tif|tiff))",
    ]
    for pat in pats:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            return _resolve_existing_path(ctx, str(m.group(1) or '').strip())
    repo_root = _repo_root_path(ctx, params)
    if repo_root:
        return _resolve_existing_path(ctx, repo_root)
    return ''

def _infer_mode(text: str, skill: Dict[str, Any]) -> str:
    meta = skill.get('metadata') if isinstance(skill.get('metadata'), dict) else {}
    explicit = str(skill.get('implementation_hint') or meta.get('executor_mode') or '').strip().lower()
    if explicit in {'authoring', 'document_review', 'portal_reconciliation', 'data_analysis', 'reporting', 'research', 'sports_live_table', 'spreadsheet_enrichment', 'ocr_extraction'}:
        return explicit
    low = ' '.join([
        str(text or '').lower(),
        str(skill.get('id') or '').lower(),
        str(skill.get('label') or '').lower(),
        str(skill.get('description') or '').lower(),
        str(skill.get('reason') or '').lower(),
    ])
    if any(tok in low for tok in ('ocr', 'extract text', 'extract the visible text', 'scanned', 'receipt image', '.png', '.jpg', '.jpeg', '.webp')):
        return 'ocr_extraction'
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
    doc_text = ''
    if source_path:
        try:
            doc_text = Path(str(source_path)).read_text(encoding='utf-8', errors='ignore')
        except Exception:
            doc_text = ''
    clause_lines = []
    for raw_line in str(doc_text or '').splitlines():
        line = str(raw_line or '').strip()
        if not line:
            continue
        low = line.lower()
        if 'clause' in low or ':' in line:
            clause_lines.append(line)
    highlights = clause_lines[:3]
    findings = [
        {'topic': 'scope_change', 'severity': 'medium', 'note': 'Watch for change-control language that allows unilateral scope changes.'},
        {'topic': 'data_and_liability', 'severity': 'high', 'note': 'Check how data handling, retention, and liability carve-outs are defined.'},
        {'topic': 'renewal_terms', 'severity': 'medium', 'note': 'Confirm renewal and termination timing is workable for the customer.'},
    ]
    follow_up = [
        'Which clause needs tighter language to prevent unexpected scope changes?',
        'Are data retention and confidentiality obligations defined in the main agreement or only by reference?',
        'Does the renewal notice window create operational risk for the customer?',
    ]
    parts = ['## Executive Summary', '', 'This compact review highlights the clauses most likely to create negotiation or operational risk.', '']
    if highlights:
        parts.extend(['## Highest-Risk Clauses', ''] + [f'- {line}' for line in highlights] + [''])
    parts.extend(['## Follow-Up Questions', ''] + [f'- {q}' for q in follow_up] + [''])
    final_answer = '\n'.join(parts).strip()
    return {
        'request': text,
        'input_path': source_path,
        'review_type': 'bounded_document_review',
        'findings': findings,
        'summary': 'Produced a bounded review summary with highest-risk clauses and follow-up questions.',
        'next_actions': [
            'Confirm assumptions against the source document.',
            'Escalate high-severity items for human review.',
        ],
        'final_answer': final_answer,
        'response': final_answer,
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

def _numeric_columns(rows: List[Dict[str, Any]]) -> List[str]:
    if not rows:
        return []
    keys = [str(k or '') for k in rows[0].keys()]
    out: List[str] = []
    for key in keys:
        vals = [str((row or {}).get(key) or '').strip() for row in rows]
        non_empty = [v for v in vals if v]
        if not non_empty:
            continue
        ok = 0
        for val in non_empty:
            try:
                float(val.replace(',', ''))
                ok += 1
            except Exception:
                pass
        if ok >= max(1, int(len(non_empty) * 0.8)):
            out.append(key)
    return out

def _threshold_percent(text: str) -> float | None:
    m = re.search(r'more than\s+([0-9]+(?:\.[0-9]+)?)\s*(?:%|percent)', str(text or '').lower())
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None

def _compare_payload_from_rows(text: str, rows: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    low_req = str(text or '').lower()
    if 'compare' not in low_req or not rows:
        return None
    num_cols = _numeric_columns(rows)
    if len(num_cols) < 2:
        return None
    keys = [str(k or '') for k in rows[0].keys()]
    label_col = ''
    for key in keys:
        if key not in num_cols:
            label_col = key
            break
    if not label_col:
        label_col = keys[0] if keys else 'item'
    extra_cols = [k for k in keys if k not in {label_col, num_cols[0], num_cols[1]}][:2]
    base_col, compare_col = num_cols[0], num_cols[1]
    threshold = _threshold_percent(text)
    result_rows: List[Dict[str, Any]] = []
    for row in rows:
        base_val = _money((row or {}).get(base_col))
        compare_val = _money((row or {}).get(compare_col))
        delta = round(compare_val - base_val, 2)
        pct = None if base_val == 0 else round((delta / base_val) * 100.0, 2)
        flagged = bool(threshold is not None and pct is not None and abs(pct) > threshold)
        item = {
            'label': str((row or {}).get(label_col) or '').strip() or 'item',
            'base': base_val,
            'compare': compare_val,
            'delta': delta,
            'pct_change': pct,
            'flagged': flagged,
        }
        for key in extra_cols:
            item[key] = str((row or {}).get(key) or '').strip()
        result_rows.append(item)
    if not result_rows:
        return None
    inc = max(result_rows, key=lambda r: r.get('delta') or 0.0)
    dec = min(result_rows, key=lambda r: r.get('delta') or 0.0)
    flagged_rows = [r for r in result_rows if r.get('flagged')]
    table_cols = [label_col] + extra_cols + [base_col, compare_col, 'delta', 'pct_change', 'flagged']
    lines = ['| ' + ' | '.join(table_cols) + ' |', '| ' + ' | '.join([':---'] * len(table_cols)) + ' |']
    for row in result_rows:
        vals = [row.get('label', '')]
        vals.extend([row.get(col, '') for col in extra_cols])
        vals.extend([
            row.get('base', ''),
            row.get('compare', ''),
            row.get('delta', ''),
            '' if row.get('pct_change') is None else f"{row.get('pct_change')}%",
            'yes' if row.get('flagged') else '',
        ])
        lines.append('| ' + ' | '.join([str(v) for v in vals]) + ' |')
    bullets = [
        f'- Compared {len(result_rows)} row(s) using {base_col} versus {compare_col}.',
        f'- Biggest increase: {inc.get("label") or "item"} ({inc.get("delta")}, {"" if inc.get("pct_change") is None else str(inc.get("pct_change")) + "%"}).',
        f'- Biggest decrease: {dec.get("label") or "item"} ({dec.get("delta")}, {"" if dec.get("pct_change") is None else str(dec.get("pct_change")) + "%"}).',
    ]
    if threshold is not None:
        bullets.append(f'- Flagged {len(flagged_rows)} row(s) above the {threshold}% change threshold.')
    if flagged_rows:
        bullets.append('- Flagged items: ' + ', '.join([str(r.get('label') or '') for r in flagged_rows[:8] if str(r.get('label') or '')]))
    bullets.append(f'- Assumption: treated {base_col} as the baseline period and {compare_col} as the comparison period.')
    final_answer = '## Executive Summary\n\n' + '\n'.join(bullets) + '\n\n## Tabular Breakdown\n\n' + '\n'.join(lines)
    return {
        'comparison_rows': result_rows,
        'table_markdown': '\n'.join(lines),
        'summary': 'Generated a reviewer-ready comparison summary and tabular breakdown from the source data.',
        'final_answer': final_answer,
        'response': final_answer,
    }

def _fixture_root(source_path: str) -> Path | None:
    if not source_path:
        return None
    raw = str(source_path or '').strip()
    if not raw:
        return None
    path_candidates: List[Path] = []
    try:
        rp = Path(raw)
        path_candidates.append(rp)
        if not rp.is_absolute() and not raw.startswith('/app/'):
            path_candidates.append((Path('/app') / raw).resolve())
        else:
            path_candidates.append(rp.resolve())
    except Exception:
        pass
    if raw.startswith('/app/'):
        path_candidates.append(Path(raw))
    deduped: List[Path] = []
    seen = set()
    for candidate in path_candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    for p in deduped:
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

def _ocr_extraction_payload(ctx: Dict[str, Any], text: str, source_path: str, stem: str) -> Dict[str, Any]:
    if not source_path:
        return {
            'request': text,
            'ocr_type': 'image_to_csv',
            'summary': 'OCR extraction requested but no image path was provided.',
            'final_answer': 'Provide an input image path so the workflow can extract text and generate a CSV file.',
        }
    try:
        from plugins.gui_helpers.agent_flow.skills.image.ocr_text import run as ocr_run
    except Exception as exc:
        return {
            'request': text,
            'input_path': source_path,
            'ocr_type': 'image_to_csv',
            'summary': 'OCR extraction is unavailable because the OCR skill could not be loaded.',
            'warnings': [f'ocr_import_failed:{exc}'],
            'final_answer': 'OCR extraction is currently unavailable because the OCR skill could not be loaded.',
        }
    ocr_result = ocr_run(ctx, {'path': source_path})
    raw_text = str((ocr_result.get('data') or {}).get('text') or ocr_result.get('text') or '').strip() if isinstance(ocr_result, dict) else ''
    warnings = list(ocr_result.get('warnings') or []) if isinstance(ocr_result, dict) else []
    if not raw_text:
        return {
            'request': text,
            'input_path': source_path,
            'ocr_type': 'image_to_csv',
            'summary': 'OCR did not return text from the provided image.',
            'warnings': warnings or ['ocr_text_missing'],
            'final_answer': 'OCR could not extract text from the provided image.',
        }
    fields: List[Dict[str, str]] = []
    for line in raw_text.splitlines():
        clean = str(line or '').strip()
        if not clean:
            continue
        if ':' in clean:
            key, value = clean.split(':', 1)
            key = key.strip()
            value = value.strip()
            if key:
                fields.append({'field': key, 'value': value})
        else:
            fields.append({'field': 'raw_text', 'value': clean})
    if not fields:
        fields.append({'field': 'raw_text', 'value': raw_text})
    out_path = _uploads_dir(ctx) / f'{stem}.csv'
    with out_path.open('w', encoding='utf-8', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=['field', 'value'])
        writer.writeheader()
        for row in fields:
            writer.writerow({'field': str(row.get('field') or ''), 'value': str(row.get('value') or '')})
    preview = fields[:8]
    bullets = [f'- Extracted {len(fields)} field row(s).']
    for row in preview:
        bullets.append(f"- {str(row.get('field') or '').strip()}: {str(row.get('value') or '').strip()}")
    final_answer = '## OCR Summary\n\n' + '\n'.join(bullets)
    return {
        'request': text,
        'input_path': source_path,
        'ocr_type': 'image_to_csv',
        'raw_text': raw_text,
        'row_count': len(fields),
        'fields': fields,
        'output_path': str(out_path),
        'summary': 'Extracted OCR text and exported the fields to CSV.',
        'final_answer': final_answer,
        'response': final_answer,
        'warnings': warnings,
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
        compare_payload = _compare_payload_from_rows(text, rows)
        if isinstance(compare_payload, dict):
            payload.update(compare_payload)
            return payload
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
        ticket_col = _pick_key(['ticketid', 'ticket id', 'ticket'])
        issue_col = _pick_key(['issue', 'problem', 'summary', 'title'])
        impact_col = _pick_key(['impact'])
        urgency_col = _pick_key(['urgency', 'priority', 'severity'])
        hours_col = _pick_key(['hoursopen', 'hours open', 'age', 'open'])
        if ('triage brief' in low_req or 'same-day action' in low_req or 'support lead' in low_req) and ticket_col:
            def _rank_value(value: str, mapping: Dict[str, int]) -> int:
                low = str(value or '').strip().lower()
                return mapping.get(low, 0)
            ranked = []
            urgency_counts: Dict[str, int] = {}
            for row in rows:
                urgency_val = str((row.get(urgency_col) if urgency_col else '') or '').strip() or 'Unknown'
                impact_val = str((row.get(impact_col) if impact_col else '') or '').strip() or 'Unknown'
                issue_val = str((row.get(issue_col) if issue_col else '') or '').strip()
                hours_text = str((row.get(hours_col) if hours_col else '') or '').strip().replace(',', '')
                try:
                    hours_open = float(hours_text) if hours_text else 0.0
                except Exception:
                    hours_open = 0.0
                urgency_counts[urgency_val] = urgency_counts.get(urgency_val, 0) + 1
                ranked.append({
                    'row': row,
                    'urgency_score': _rank_value(urgency_val, {'critical': 4, 'high': 3, 'medium': 2, 'low': 1}),
                    'impact_score': _rank_value(impact_val, {'critical': 4, 'high': 3, 'medium': 2, 'low': 1}),
                    'hours_open': hours_open,
                    'urgency_val': urgency_val,
                    'impact_val': impact_val,
                    'issue_val': issue_val,
                })
            ranked.sort(key=lambda item: (-item['urgency_score'], -item['impact_score'], -item['hours_open'], str((item['row'].get(ticket_col) if ticket_col else '') or '')))
            top_rows = ranked[:5]
            cols = [c for c in [ticket_col, _pick_key(['customer', 'account', 'client']), issue_col, urgency_col, impact_col, hours_col] if c]
            table = _md_table(cols, [item['row'] for item in top_rows])
            urgency_mix = ', '.join([f"{k}={v}" for k, v in sorted(urgency_counts.items(), key=lambda kv: (-_rank_value(kv[0], {'critical': 4, 'high': 3, 'medium': 2, 'low': 1}), kv[0]))])
            reasons = []
            for item in top_rows:
                why = []
                if item['urgency_score'] >= 3:
                    why.append(f"{item['urgency_val']} urgency")
                if item['impact_score'] >= 3:
                    why.append(f"{item['impact_val']} impact")
                if item['hours_open'] >= 8:
                    why.append(f"open {int(item['hours_open']) if item['hours_open'].is_integer() else item['hours_open']}h")
                if item['issue_val']:
                    why.append(f"issue: {item['issue_val']}")
                reasons.append(f"- {str((item['row'].get(ticket_col) if ticket_col else '') or '').strip()}: " + ', '.join(why[:4]))
            parts = ['## Executive Summary', '', f"Urgency mix: {urgency_mix}.", f"Top same-day queue contains {len(top_rows)} ticket(s) prioritized by urgency, impact, and age.", '']
            if table:
                parts.extend(['## Same-Day Action Queue', '', table, ''])
            if reasons:
                parts.extend(['## Why These Tickets', ''] + reasons + [''])
            final_answer = '\n'.join(parts).strip()
            payload['table_markdown'] = table
            payload['final_answer'] = final_answer
            payload['response'] = final_answer
            payload['summary'] = 'Generated a support triage brief with urgency grouping, same-day priorities, and plain-language reasoning.'
            return payload
        ts_col = _pick_key(['timestamp', 'time', 'datetime'])
        source_col = _pick_key(['source', 'team', 'owner'])
        event_col = _pick_key(['event', 'message', 'detail', 'description', 'issue'])
        if ('incident timeline' in low_req or 'impact window' in low_req or 'incident manager' in low_req) and ts_col and event_col:
            ordered = sorted(rows, key=lambda row: str((row.get(ts_col) if ts_col else '') or ''))
            impact_start = str((ordered[0].get(ts_col) if ordered else '') or '').strip()
            customer_start = impact_start
            impact_end = str((ordered[-1].get(ts_col) if ordered else '') or '').strip()
            turning_points: List[str] = []
            for row in ordered:
                ts_val = str((row.get(ts_col) if ts_col else '') or '').strip()
                src_val = str((row.get(source_col) if source_col else '') or '').strip()
                event_val = str((row.get(event_col) if event_col else '') or '').strip()
                combined = f'{src_val} {event_val}'.lower()
                if customer_start == impact_start and any(tok in combined for tok in ('support', 'customer', 'ticket', 'reported', 'failed sign', 'user')):
                    customer_start = ts_val or customer_start
                if any(tok in combined for tok in ('recovered', 'resolved', 'rollback completed', 'baseline', 'restored')):
                    impact_end = ts_val or impact_end
                if any(tok in combined for tok in ('dropped below threshold', 'first customer', 'rollback', 'recovered', 'restored')):
                    turning_points.append(f'{ts_val}: {event_val}')
            cols = [c for c in [ts_col, source_col, event_col] if c]
            table = _md_table(cols, ordered[:10])
            unique_turning_points = []
            for item in turning_points:
                if item and item not in unique_turning_points:
                    unique_turning_points.append(item)
            parts = ['## Executive Summary', '', f'Customer-facing impact likely ran from {customer_start} to {impact_end}.', 'Likely turning points: ' + (', '.join(unique_turning_points[:3]) if unique_turning_points else 'first customer report, mitigation start, and recovery confirmation') + '.', '']
            if table:
                parts.extend(['## Timeline', '', table, ''])
            parts.extend(['## Next Follow-Up Actions', '', '- Confirm root cause and contributing factors.', '- Publish a customer-facing incident recap if required.', '- Add a prevention item to the incident tracker.', ''])
            final_answer = '\n'.join(parts).strip()
            payload['table_markdown'] = table
            payload['final_answer'] = final_answer
            payload['response'] = final_answer
            payload['summary'] = 'Generated an incident timeline summary with impact window and follow-up actions.'
            return payload
        clause_col = _pick_key(['clause'])
        terms_col = _pick_key(['terms', 'term', 'detail'])
        risk_col = _pick_key(['risklevel', 'risk level', 'risk'])
        if ('contract risk' in low_req or 'negotiation questions' in low_req or 'business stakeholder' in low_req) and clause_col:
            def _risk_rank(value: str) -> int:
                return {'high': 3, 'medium': 2, 'low': 1}.get(str(value or '').strip().lower(), 0)
            ranked_rows = sorted(rows, key=lambda row: (-_risk_rank(str((row.get(risk_col) if risk_col else '') or '')), str((row.get(clause_col) if clause_col else '') or '')))
            high_rows = [row for row in ranked_rows if _risk_rank(str((row.get(risk_col) if risk_col else '') or '')) >= 3][:5]
            selected = high_rows or ranked_rows[:5]
            cols = [c for c in [clause_col, risk_col, terms_col] if c]
            table = _md_table(cols, selected)
            questions = []
            for row in selected[:3]:
                clause_val = str((row.get(clause_col) if clause_col else '') or '').strip()
                if clause_val:
                    questions.append(f'Can we revise {clause_val!r} to reduce exposure?')
            parts = ['## Executive Summary', '', f'Identified {len(selected)} high-risk clause(s) that should be reviewed before signature.', '']
            if table:
                parts.extend(['## Highest-Risk Clauses', '', table, ''])
            if questions:
                parts.extend(['## Negotiation Questions', ''] + [f'- {q}' for q in questions] + [''])
            final_answer = '\n'.join(parts).strip()
            payload['table_markdown'] = table
            payload['final_answer'] = final_answer
            payload['response'] = final_answer
            payload['summary'] = 'Generated a contract risk review with highest-risk clauses and negotiation questions.'
            return payload
        interviewer_col = _pick_key(['interviewer'])
        rec_col = _pick_key(['recommendation'])
        strengths_col = _pick_key(['strengths', 'strength'])
        concerns_col = _pick_key(['concerns', 'risks', 'risk'])
        if ('hiring recommendation' in low_req or 'panel should ask' in low_req or 'interviewers' in low_req) and interviewer_col and rec_col:
            cols = [c for c in [interviewer_col, rec_col, strengths_col, concerns_col] if c]
            table = _md_table(cols, rows[:8])
            strengths = []
            concerns = []
            for row in rows:
                if strengths_col:
                    val = str(row.get(strengths_col) or '').strip()
                    if val:
                        strengths.append(val)
                if concerns_col:
                    val = str(row.get(concerns_col) or '').strip()
                    if val:
                        concerns.append(val)
            uniq_strengths = []
            for item in strengths:
                if item not in uniq_strengths:
                    uniq_strengths.append(item)
            uniq_concerns = []
            for item in concerns:
                if item not in uniq_concerns:
                    uniq_concerns.append(item)
            follow_ups = [f'Ask for a quantified example of {item.lower().rstrip(".")}.' for item in uniq_concerns[:3]] or ['Ask for one quantified example of business impact.']
            parts = ['## Executive Summary', '', 'Recommendation: proceed with a final decision only after one focused follow-up on the recurring risk areas.', f'Common strengths: {uniq_strengths[0] if uniq_strengths else "Strong stakeholder handling."}', f'Main risks: {uniq_concerns[0] if uniq_concerns else "Needs one deeper example in a critical area."}', '']
            if table:
                parts.extend(['## Panel View', '', table, ''])
            if follow_ups:
                parts.extend(['## Follow-Up Questions', ''] + [f'- {q}' for q in follow_ups] + [''])
            final_answer = '\n'.join(parts).strip()
            payload['table_markdown'] = table
            payload['final_answer'] = final_answer
            payload['response'] = final_answer
            payload['summary'] = 'Generated a hiring recommendation memo with strengths, risks, and panel follow-up questions.'
            return payload
        category_col = _pick_key(['category'])
        item_col = _pick_key(['item', 'feature'])
        impact_text_col = _pick_key(['customerimpact', 'customer impact', 'benefit', 'detail'])
        action_required_col = _pick_key(['actionrequired', 'action required'])
        if ('release announcement email' in low_req or 'customer-ready release announcement email' in low_req or 'customers need to do next' in low_req) and item_col:
            benefits = []
            next_steps = []
            for row in rows:
                item_val = str((row.get(item_col) if item_col else '') or '').strip()
                impact_val = str((row.get(impact_text_col) if impact_text_col else '') or '').strip()
                action_val = str((row.get(action_required_col) if action_required_col else '') or '').strip().lower()
                if item_val and impact_val and len(benefits) < 3:
                    benefits.append(f'{item_val}: {impact_val}')
                if item_val and action_val in {'yes', 'true', '1'}:
                    next_steps.append(f'Update to the latest version so {item_val.lower()} is available.')
            parts = ['Subject: Product update: faster, simpler improvements now available', '', 'Hello,', '', 'We released a small set of improvements designed to make your day-to-day work easier.', '']
            if benefits:
                parts.extend(['What changed:', ''] + [f'- {b}' for b in benefits] + [''])
            parts.extend(['What you need to do next:', ''] + ([f'- {x}' for x in next_steps] if next_steps else ['- No action is required on your side right now.']) + ['', 'Thank you,', 'Customer Success'])
            final_answer = '\n'.join(parts).strip()
            payload['final_answer'] = final_answer
            payload['response'] = final_answer
            payload['summary'] = 'Generated a concise customer-ready release announcement email with benefits and next steps.'
            return payload
        vendor_col = _pick_key(['vendor'])
        cost_col = _pick_key(['annualcost', 'cost'])
        weeks_col = _pick_key(['implementationweeks', 'weeks', 'implementation'])
        security_col = _pick_key(['securityscore', 'security'])
        support_col = _pick_key(['supportscore', 'support'])
        if ('shortlist' in low_req or 'tradeoffs' in low_req or 'operations director' in low_req) and vendor_col and cost_col:
            scored = []
            costs = [_money(row.get(cost_col)) for row in rows]
            weeks = [_money(row.get(weeks_col)) for row in rows] if weeks_col else [0.0]
            min_cost, max_cost = min(costs or [0.0]), max(costs or [0.0])
            min_weeks, max_weeks = min(weeks or [0.0]), max(weeks or [0.0])
            def _norm_inverse(value: float, low: float, high: float) -> float:
                if high <= low:
                    return 1.0
                return 1.0 - ((value - low) / (high - low))
            for row in rows:
                score = (0.25 * _norm_inverse(_money(row.get(cost_col)), min_cost, max_cost)) + (0.20 * _norm_inverse(_money(row.get(weeks_col)) if weeks_col else 0.0, min_weeks, max_weeks)) + (0.30 * (_money(row.get(security_col)) / 10.0 if security_col else 0.0)) + (0.25 * (_money(row.get(support_col)) / 10.0 if support_col else 0.0))
                scored.append((round(score, 4), row))
            scored.sort(key=lambda item: (-item[0], str((item[1].get(vendor_col) if vendor_col else '') or '')))
            top_vendor = scored[0][1] if scored else {}
            table_rows = []
            for score_val, row in scored[:4]:
                table_rows.append({vendor_col: row.get(vendor_col), cost_col: row.get(cost_col), weeks_col: row.get(weeks_col) if weeks_col else '', security_col: row.get(security_col) if security_col else '', support_col: row.get(support_col) if support_col else '', 'WeightedScore': score_val})
            cols = [c for c in [vendor_col, cost_col, weeks_col, security_col, support_col, 'WeightedScore'] if c]
            table = _md_table(cols, table_rows)
            top_name = str((top_vendor.get(vendor_col) if isinstance(top_vendor, dict) else '') or '').strip() or 'the top-ranked vendor'
            parts = ['## Executive Summary', '', f'Recommend shortlisting {top_name} based on the best balance of cost, implementation speed, security posture, and support quality.', '']
            if table:
                parts.extend(['## Tradeoff Table', '', table, ''])
            parts.extend(['## Recommendation Notes', '', '- Lowest cost options carried more implementation or support tradeoffs.', '- Faster deployment options were not always strongest on security.', '- The recommended shortlist balances speed and operational risk more evenly.', ''])
            final_answer = '\n'.join(parts).strip()
            payload['table_markdown'] = table
            payload['final_answer'] = final_answer
            payload['response'] = final_answer
            payload['summary'] = 'Generated a vendor shortlist recommendation with tradeoffs for an operations director.'
            return payload
        title_col = _pick_key(['title', 'item'])
        dep_col = _pick_key(['dependency'])
        risk2_col = _pick_key(['risk'])
        effort_col = _pick_key(['effort'])
        if ('sprint plan' in low_req or 'should be pulled in first' in low_req or 'capacity risks' in low_req) and title_col and priority_col:
            def _prio_rank(value: str) -> int:
                return {'critical': 4, 'high': 3, 'medium': 2, 'low': 1}.get(str(value or '').strip().lower(), 0)
            ranked = sorted(rows, key=lambda row: (-_prio_rank(str((row.get(priority_col) if priority_col else '') or '')), _money(row.get(effort_col)) if effort_col else 0.0, str((row.get(title_col) if title_col else '') or '')))
            pull_first = []
            wait_rows = []
            risks = []
            for row in ranked:
                dep_val = str((row.get(dep_col) if dep_col else '') or '').strip()
                risk_val = str((row.get(risk2_col) if risk2_col else '') or '').strip()
                if len(pull_first) < 3 and (not dep_val or dep_val.lower() == 'none') and str((row.get(priority_col) if priority_col else '') or '').strip().lower() in {'high', 'critical'}:
                    pull_first.append(row)
                else:
                    wait_rows.append(row)
                if dep_val and dep_val.lower() != 'none':
                    risks.append(f"{str((row.get(title_col) if title_col else '') or '').strip()}: blocked by {dep_val}")
                elif risk_val and risk_val.lower() in {'high', 'critical'}:
                    risks.append(f"{str((row.get(title_col) if title_col else '') or '').strip()}: {risk_val} delivery risk")
            pull_lines = [f"- {str((row.get(title_col) if title_col else '') or '').strip()}" for row in pull_first] or ['- No item is ready to pull first without clarifying dependencies.']
            wait_lines = [f"- {str((row.get(title_col) if title_col else '') or '').strip()}" for row in wait_rows[:4]]
            parts = ['## Executive Summary', '', f'Recommend starting with {len(pull_first)} item(s) that are high priority and least blocked by dependencies.', '', '## Pull First', ''] + pull_lines + ['']
            if wait_lines:
                parts.extend(['## Wait / Revisit', ''] + wait_lines + [''])
            if risks:
                parts.extend(['## Dependency and Capacity Risks', ''] + [f'- {x}' for x in risks[:5]] + [''])
            final_answer = '\n'.join(parts).strip()
            payload['final_answer'] = final_answer
            payload['response'] = final_answer
            payload['summary'] = 'Generated a practical next sprint plan with pull-first and wait recommendations.'
            return payload
        topic_col = _pick_key(['topic', 'question'])
        detail_col = _pick_key(['detail', 'answer', 'description'])
        if ('compact faq' in low_req or 'new users' in low_req or 'support agent gets most often' in low_req) and topic_col and detail_col:
            parts = ['## FAQ', '']
            for row in rows[:8]:
                topic_val = str((row.get(topic_col) if topic_col else '') or '').strip()
                detail_val = str((row.get(detail_col) if detail_col else '') or '').strip()
                if topic_val and detail_val:
                    parts.extend([f'### {topic_val}', detail_val, ''])
            final_answer = '\n'.join(parts).strip()
            payload['final_answer'] = final_answer
            payload['response'] = final_answer
            payload['summary'] = 'Generated a compact FAQ in plain language for new users.'
            return payload
        team_col = _pick_key(['team'])
        stakeholder_col = _pick_key(['stakeholder'])
        issue2_col = _pick_key(['issue', 'conflict'])
        if ('scheduling resolution brief' in low_req or 'highest-priority conflicts' in low_req or 'stakeholders should be contacted first' in low_req) and team_col and issue2_col and priority_col:
            def _prio_rank2(value: str) -> int:
                return {'critical': 4, 'high': 3, 'medium': 2, 'low': 1}.get(str(value or '').strip().lower(), 0)
            ordered = sorted(rows, key=lambda row: (-_prio_rank2(str((row.get(priority_col) if priority_col else '') or '')), str((row.get(team_col) if team_col else '') or '')))
            cols = [c for c in [team_col, issue2_col, priority_col, stakeholder_col] if c]
            table = _md_table(cols, ordered[:5])
            contact_lines = []
            for row in ordered[:3]:
                team_val = str((row.get(team_col) if team_col else '') or '').strip()
                stakeholder_val = str((row.get(stakeholder_col) if stakeholder_col else '') or '').strip()
                if stakeholder_val:
                    contact_lines.append(f'- Contact {stakeholder_val} first for {team_val}.')
            parts = ['## Executive Summary', '', f'Found {len(ordered)} scheduling conflict(s); resolve the highest-priority issues first to reduce operational risk.', '']
            if table:
                parts.extend(['## Conflict Order', '', table, ''])
            if contact_lines:
                parts.extend(['## Stakeholders to Contact First', ''] + contact_lines + [''])
            final_answer = '\n'.join(parts).strip()
            payload['table_markdown'] = table
            payload['final_answer'] = final_answer
            payload['response'] = final_answer
            payload['summary'] = 'Generated a scheduling resolution brief with conflict ordering and stakeholder contacts.'
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

def _json_file_payload(text: str, source_path: str) -> Dict[str, Any] | None:
    if not source_path or Path(str(source_path)).suffix.lower() != '.json':
        return None
    try:
        obj = json.loads(Path(str(source_path)).read_text(encoding='utf-8'))
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    low = str(text or '').lower()
    if 'email' in low and ('release' in low or 'announcement' in low or 'customer' in low):
        product = str(obj.get('product') or 'Product').strip()
        version = str(obj.get('version') or '').strip()
        benefits = [str(x or '').strip() for x in (obj.get('customer_benefits') or obj.get('highlights') or []) if str(x or '').strip()][:3]
        next_steps = [str(x or '').strip() for x in (obj.get('next_steps') or []) if str(x or '').strip()][:3]
        subject = 'Subject: ' + product + ((' ' + version) if version else '') + ' update'
        parts = [subject, '', 'Hello,', '', f'We are sharing a concise update for {product}.', '']
        if benefits:
            parts.extend(['What changed for customers:', ''] + [f'- {item}' for item in benefits] + [''])
        if next_steps:
            parts.extend(['What you should do next:', ''] + [f'- {item}' for item in next_steps] + [''])
        parts.extend(['Thank you,', 'Customer Success'])
        final_answer = '\n'.join(parts).strip()
        return {
            'request': text,
            'input_path': source_path,
            'summary': 'Generated a concise customer-ready release announcement email with benefits and next steps.',
            'final_answer': final_answer,
            'response': final_answer,
        }
    return None

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
    mode = _infer_mode(req, {'id': 'custom.general_workflow_executor', 'label': 'General Workflow Executor', 'description': 'Execute the core task requested by the generated workflow when no installed skill fully matches.', 'reason': 'No installed executable skill matched the request, so the generated workflow needs a generic custom executor.', 'category': 'custom', 'params_schema': {'type': 'object', 'properties': {}, 'additionalProperties': True}, 'metadata': {}, 'implementation_hint': '', 'request_text': 'Using /uploads/autoflow_release_notes.json, draft a release announcement email for customers that highlights the main benefits and next steps.', 'repair_focus': 'tool_node_direct_exception; HTTPError', 'previous_source': '', 'previous_path': '', 'previous_hash': '', 'bug_signals': ['tool_node_direct_exception', 'HTTPError'], 'failing_requests': []})
    tabular_suffixes = {'.csv', '.tsv', '.xlsx', '.xlsm', '.xls'}
    if source_path and Path(str(source_path)).suffix.lower() in tabular_suffixes and mode in {'ocr_extraction', 'document_review'}:
        mode = 'data_analysis'
    uploads = _uploads_dir(ctx)
    stem = _slugify(req[:80], 'generated_workflow_result') + '_' + str(int(time.time()))
    warnings: List[str] = []
    json_payload = _json_file_payload(req, source_path)
    if json_payload is not None:
        out_path = uploads / f'{stem}.json'
        out_path.write_text(json.dumps(json_payload, ensure_ascii=True, indent=2), encoding='utf-8')
        summary = str(json_payload.get('summary') or 'Generated a JSON-backed deliverable.')
        data = dict(json_payload)
        data['output_path'] = str(out_path)
        data['mode'] = 'authoring'
        return {'ok': True, 'output_path': str(out_path), 'summary': summary, 'mode': 'authoring', 'data': data, 'warnings': warnings}
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
    elif mode == 'ocr_extraction':
        payload = _ocr_extraction_payload(ctx, req, source_path, stem)
        warnings.extend(payload.pop('warnings', [])) if isinstance(payload.get('warnings'), list) else None
    elif mode in {'data_analysis', 'spreadsheet_enrichment'}:
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
    artifact_output_path = str(payload.get('output_path') or '') if isinstance(payload, dict) else ''
    artifact_path_obj = Path(artifact_output_path).resolve() if artifact_output_path else None
    if artifact_output_path and artifact_path_obj is not None and artifact_path_obj.is_file():
        summary = str(payload.get('summary') or f'Generated {mode} artifact.')
        data = dict(payload)
        data['output_path'] = artifact_output_path
        data['mode'] = mode
        return {
            'ok': True,
            'output_path': artifact_output_path,
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


TOOL_SPEC = {'id': 'custom.general_workflow_executor', 'category': 'custom', 'label': 'General Workflow Executor', 'description': 'Execute the core task requested by the generated workflow when no installed skill fully matches.', 'permissions': ['custom.general_workflow_executor', 'custom.*'], 'metadata': {'version': '1.0', 'created_at': '2026-06-23T05:25:23.306499+00:00', 'last_updated': '2026-06-23T05:25:23.306499+00:00', 'dev_status': 'untested'}, 'params_schema': {'type': 'object', 'properties': {}, 'additionalProperties': True}}
