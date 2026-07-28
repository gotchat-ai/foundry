from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

NAME = 'custom.awf_create_me_a_workflow_that_can_look_up_sports_game_for_any_games_that_is__create_me_a_workflow_that_can_look_up_sports_game_for_any_games_that_is_executor'
PERMISSIONS = ['custom.awf_create_me_a_workflow_that_can_look_up_sports_game_for_any_games_that_is__create_me_a_workflow_that_can_look_up_sports_game_for_any_games_that_is_executor', 'custom.*']

LEAGUES = [
    ('baseball', 'mlb'),
    ('basketball', 'nba'),
    ('football', 'nfl'),
    ('hockey', 'nhl'),
]

def _uploads_dir(ctx: Dict[str, Any]) -> Path:
    app = (ctx or {}).get('app')
    data_dir = getattr(getattr(app, 'state', None), 'data_dir', None) if app is not None else None
    root = Path(str(data_dir or './data')).resolve() / 'uploads'
    root.mkdir(parents=True, exist_ok=True)
    return root

def _json_get(url: str, timeout: float) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={'Accept': 'application/json'}, method='GET')
    with urllib.request.urlopen(req, timeout=max(3.0, min(float(timeout or 10.0), 20.0))) as resp:
        raw = resp.read().decode('utf-8', 'ignore')
    row = json.loads(raw)
    return row if isinstance(row, dict) else {}

def _status_text(comp: Dict[str, Any]) -> str:
    state = str((((comp.get('status') or {}).get('type') or {}).get('state') or '')).strip().lower()
    detail = str((((comp.get('status') or {}).get('type') or {}).get('shortDetail') or '')).strip()
    if detail:
        return detail
    return state or 'unknown'

def _is_live(comp: Dict[str, Any]) -> bool:
    state = str((((comp.get('status') or {}).get('type') or {}).get('state') or '')).strip().lower()
    detail = _status_text(comp).lower()
    return state in {'in', 'live'} or 'live' in detail or 'qtr' in detail or 'half' in detail or 'period' in detail

def _requested_leagues(request_text: str) -> List[tuple[str, str]]:
    low = str(request_text or '').lower()
    if any(tok in low for tok in ('basketball', 'nba', 'wnba')):
        return [('basketball', 'nba'), ('basketball', 'wnba')]
    if any(tok in low for tok in ('football', 'nfl')):
        return [('football', 'nfl')]
    if any(tok in low for tok in ('baseball', 'mlb')):
        return [('baseball', 'mlb')]
    if any(tok in low for tok in ('hockey', 'nhl')):
        return [('hockey', 'nhl')]
    return LEAGUES

def _requested_limit(request_text: str) -> int:
    import re
    m = re.search(r'\b(\d{1,2})\b', str(request_text or ''))
    if not m:
        return 10
    try:
        return max(1, min(int(m.group(1)), 25))
    except Exception:
        return 10

def _fetch_games(timeout: float, request_text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for sport, league in _requested_leagues(request_text):
        url = f'https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard'
        try:
            payload = _json_get(url, timeout)
        except Exception:
            continue
        events = payload.get('events') if isinstance(payload.get('events'), list) else []
        for event in events:
            if not isinstance(event, dict):
                continue
            comps = event.get('competitions') if isinstance(event.get('competitions'), list) else []
            comp = comps[0] if comps and isinstance(comps[0], dict) else {}
            if not _is_live(comp):
                continue
            competitors = comp.get('competitors') if isinstance(comp.get('competitors'), list) else []
            away = competitors[0] if len(competitors) > 0 and isinstance(competitors[0], dict) else {}
            home = competitors[1] if len(competitors) > 1 and isinstance(competitors[1], dict) else {}
            out.append({
                'league': league.upper(),
                'matchup': f"{str(((away.get('team') or {}).get('displayName') or 'Away')).strip()} at {str(((home.get('team') or {}).get('displayName') or 'Home')).strip()}",
                'away_score': str(away.get('score') or ''),
                'home_score': str(home.get('score') or ''),
                'status': _status_text(comp),
                'live': _is_live(comp),
            })
    live_rows = [row for row in out if row.get('live')]
    limit = _requested_limit(request_text)
    return (live_rows or out)[:limit]

def _markdown_table(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return 'No matching games found in the scoreboard feed.'
    lines = [
        '| League | Matchup | Away | Home | Status |',
        '|---|---|---:|---:|---|',
    ]
    for row in rows:
        lines.append(
            f"| {str(row.get('league') or '')} | {str(row.get('matchup') or '')} | {str(row.get('away_score') or '')} | {str(row.get('home_score') or '')} | {str(row.get('status') or '')} |"
        )
    return '\n'.join(lines)

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    timeout = float((params or {}).get('timeout') or 10.0)
    request_text = str((params or {}).get('current_request_text') or (params or {}).get('request_text') or (params or {}).get('user_request') or (params or {}).get('request') or (params or {}).get('text') or (ctx or {}).get('original_request') or '')
    rows = _fetch_games(timeout, request_text)
    stamp = str(int(time.time()))
    out = _uploads_dir(ctx) / f'sports_live_games_{stamp}.json'
    table = _markdown_table(rows)
    payload = {'games': rows, 'table_markdown': table, 'summary': f'Found {len(rows)} matching game(s).\n\n{table}'}
    out.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding='utf-8')
    return {
        'ok': True,
        'games': rows,
        'table_markdown': payload['table_markdown'],
        'summary': payload['summary'],
        'output_path': str(out),
        'data': {'games': rows, 'table_markdown': payload['table_markdown'], 'summary': payload['summary'], 'output_path': str(out)},
        'warnings': [] if rows else ['no_matching_games_found'],
    }


TOOL_SPEC = {'id': 'custom.awf_create_me_a_workflow_that_can_look_up_sports_game_for_any_games_that_is__create_me_a_workflow_that_can_look_up_sports_game_for_any_games_that_is_executor', 'category': 'custom', 'label': 'create_me_a_workflow_that_can_look_up_sports_game_for_any_games_that_is executor', 'description': 'Generated workflow executor for: Create me a workflow that can look up sports game for any games that is currently going on. Also output the games in a table view with the results if any.', 'permissions': ['custom.awf_create_me_a_workflow_that_can_look_up_sports_game_for_any_games_that_is__create_me_a_workflow_that_can_look_up_sports_game_for_any_games_that_is_executor', 'custom.*'], 'params_schema': {'type': 'object', 'properties': {'request_text': {'type': 'string'}, 'user_request': {'type': 'string'}, 'request': {'type': 'string'}, 'text': {'type': 'string'}, 'input_path': {'type': 'string'}, 'file_path': {'type': 'string'}, 'path': {'type': 'string'}}, 'additionalProperties': True}}
