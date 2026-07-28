from __future__ import annotations

import csv
import html
import json
import math
import re
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

try:
    from .._path_common import resolve_base_dir, resolve_path
except Exception:
    import importlib.util
    _P = Path(__file__).resolve().parent.parent / "_path_common.py"
    _S = importlib.util.spec_from_file_location("agent_flow_path_common", _P)
    _M = importlib.util.module_from_spec(_S)
    assert _S is not None and _S.loader is not None
    _S.loader.exec_module(_M)
    resolve_base_dir = _M.resolve_base_dir
    resolve_path = _M.resolve_path

NAME = "document.report_pack"
PERMISSIONS = [NAME, "document.*", "result.emit"]

EMU_W = 914400
SLIDE_W = 12192000
SLIDE_H = 6858000


def _safe_name(text: str, default: str = "research_report") -> str:
    raw = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(text or "").strip().lower()).strip("_")
    return (raw or default)[:80]


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value in (None, ""):
        return []
    return [value]


def _normalize_sections(params: Dict[str, Any]) -> List[Dict[str, str]]:
    sections = []
    raw = params.get("sections")
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                title = str(item.get("title") or item.get("heading") or "Section").strip()
                body = _text(item.get("body") if "body" in item else item.get("text"))
            else:
                title = "Section"
                body = _text(item)
            if title or body:
                sections.append({"title": title or "Section", "body": body})
    summary = str(params.get("summary") or params.get("executive_summary") or "").strip()
    if summary and not any(s.get("title", "").lower().startswith("executive") for s in sections):
        sections.insert(0, {"title": "Executive Summary", "body": summary})
    if not sections:
        sections = [{"title": "Executive Summary", "body": "Research pack generated from the available evidence."}]
    return sections


def _normalize_records(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key in ("records", "data", "table", "rows"):
        value = params.get(key)
        if isinstance(value, list):
            return [dict(x) for x in value if isinstance(x, dict)]
        if isinstance(value, dict) and isinstance(value.get("records"), list):
            return [dict(x) for x in value.get("records") if isinstance(x, dict)]
    evidence = params.get("evidence")
    if isinstance(evidence, dict):
        rows = []
        for key, val in evidence.items():
            if isinstance(val, (str, int, float, bool)):
                rows.append({"metric": key, "value": val})
        return rows
    return []


def _normalize_charts(params: Dict[str, Any], records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    charts = []
    raw = params.get("charts")
    if isinstance(raw, list):
        for c in raw:
            if isinstance(c, dict):
                charts.append(dict(c))
    elif isinstance(params.get("chart"), dict):
        charts.append(dict(params.get("chart") or {}))
    if charts:
        return charts
    if not records:
        return []
    sample = records[0]
    label_key = next((k for k in sample.keys() if not _is_number(sample.get(k))), None)
    value_key = next((k for k in sample.keys() if _is_number(sample.get(k))), None)
    if not label_key or not value_key:
        return []
    labels, values = [], []
    for row in records[:12]:
        label = str(row.get(label_key) or "").strip()
        val = _num(row.get(value_key))
        if label and val is not None:
            labels.append(label)
            values.append(val)
    if labels and values:
        charts.append({"title": f"{value_key} by {label_key}", "labels": labels, "values": values, "unit": str(value_key)})
    return charts


def _normalize_evidence(params: Dict[str, Any]) -> List[Dict[str, str]]:
    out = []
    for item in _as_list(params.get("sources") or params.get("evidence") or params.get("articles")):
        if isinstance(item, dict):
            title = str(item.get("title") or item.get("source") or item.get("name") or "Evidence").strip()
            url = str(item.get("url") or item.get("link") or "").strip()
            snippet = str(item.get("snippet") or item.get("content") or item.get("summary") or "").strip()
            out.append({"title": title, "url": url, "snippet": snippet})
        else:
            out.append({"title": "Evidence", "url": "", "snippet": _text(item)})
    return out[:30]


def _is_number(v: Any) -> bool:
    return _num(v) is not None


def _num(v: Any) -> float | None:
    try:
        if v in (None, ""):
            return None
        return float(str(v).replace(",", "").strip())
    except Exception:
        return None


def _docx_xml_paragraph(text: str, style: str = "") -> str:
    props = ""
    if style == "title":
        props = '<w:pPr><w:jc w:val="center"/><w:spacing w:after="240"/></w:pPr>'
        rpr = '<w:rPr><w:b/><w:sz w:val="36"/></w:rPr>'
    elif style == "heading":
        props = '<w:pPr><w:spacing w:before="280" w:after="120"/></w:pPr>'
        rpr = '<w:rPr><w:b/><w:sz w:val="26"/><w:color w:val="1F4E79"/></w:rPr>'
    else:
        props = '<w:pPr><w:spacing w:after="120"/></w:pPr>'
        rpr = '<w:rPr><w:sz w:val="22"/></w:rPr>'
    return f"<w:p>{props}<w:r>{rpr}<w:t xml:space=\"preserve\">{html.escape(str(text or ''))}</w:t></w:r></w:p>"


def _write_docx(path: Path, title: str, sections: List[Dict[str, str]], records: List[Dict[str, Any]], evidence: List[Dict[str, str]]) -> None:
    body = [_docx_xml_paragraph(title, "title")]
    for sec in sections:
        body.append(_docx_xml_paragraph(sec.get("title") or "Section", "heading"))
        for para in str(sec.get("body") or "").splitlines() or [""]:
            if para.strip():
                body.append(_docx_xml_paragraph(para.strip()))
    if records:
        body.append(_docx_xml_paragraph("Data Table", "heading"))
        headers = list(records[0].keys())[:8]
        body.append(_docx_xml_paragraph(" | ".join(headers)))
        for row in records[:20]:
            body.append(_docx_xml_paragraph(" | ".join(str(row.get(h, "")) for h in headers)))
    if evidence:
        body.append(_docx_xml_paragraph("Selected Sources", "heading"))
        for src in evidence[:12]:
            line = src.get("title", "")
            if src.get("url"):
                line += f" - {src.get('url')}"
            if src.get("snippet"):
                line += f"\n{src.get('snippet')}"
            body.append(_docx_xml_paragraph(line))
    document = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + "".join(body) + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="900" w:right="900" w:bottom="900" w:left="900"/></w:sectPr></w:body></w:document>'
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        zf.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        zf.writestr("word/document.xml", document)


def _a_text(x: int, y: int, w: int, h: int, text: str, size: int = 2400, bold: bool = False) -> str:
    b = '<a:b/>' if bold else ''
    return f'<p:sp><p:nvSpPr><p:cNvPr id="{abs(hash((x,y,text)))%100000}" name="Text"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></p:spPr><p:txBody><a:bodyPr wrap="square"/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US" sz="{size}">{b}<a:solidFill><a:srgbClr val="1F2937"/></a:solidFill></a:rPr><a:t>{html.escape(str(text or ''))}</a:t></a:r></a:p></p:txBody></p:sp>'


def _a_rect(x: int, y: int, w: int, h: int, color: str) -> str:
    return f'<p:sp><p:nvSpPr><p:cNvPr id="{abs(hash((x,y,w,h,color)))%100000}" name="Bar"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:solidFill><a:srgbClr val="{color}"/></a:solidFill><a:ln><a:noFill/></a:ln></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody></p:sp>'


def _slide_xml(title: str, body_lines: List[str], chart: Dict[str, Any] | None = None) -> str:
    shapes = [_a_text(550000, 260000, 11000000, 600000, title, 3200, True)]
    y = 1050000
    for line in body_lines[:12]:
        shapes.append(_a_text(760000, y, 10400000, 330000, line, 1700, False))
        y += 390000
    if chart:
        labels = [str(x) for x in chart.get("labels") or chart.get("x") or chart.get("categories") or []]
        values = chart.get("values")
        if not isinstance(values, list):
            series = chart.get("series") if isinstance(chart.get("series"), list) else []
            values = (series[0].get("y") or series[0].get("values")) if series and isinstance(series[0], dict) else []
        nums = [_num(v) or 0 for v in values]
        if labels and nums:
            maxv = max(max(nums), 1)
            base_x, base_y, bar_w, gap = 900000, 5100000, 520000, 160000
            for idx, (lab, val) in enumerate(zip(labels[:10], nums[:10])):
                h = int(1700000 * (val / maxv))
                x = base_x + idx * (bar_w + gap)
                shapes.append(_a_rect(x, base_y - h, bar_w, h, "2563EB"))
                shapes.append(_a_text(x-60000, base_y+80000, bar_w+120000, 250000, lab[:10], 900, False))
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="F8FAFC"/></a:solidFill><a:effectLst/></p:bgPr></p:bg><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>' + "".join(shapes) + '</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>'


def _write_pptx(path: Path, title: str, sections: List[Dict[str, str]], charts: List[Dict[str, Any]], evidence: List[Dict[str, str]]) -> None:
    slides = []
    slides.append(_slide_xml(title, ["Executive data briefing", f"Generated {time.strftime('%Y-%m-%d')}"]))
    for sec in sections[:3]:
        lines = [ln.strip() for ln in str(sec.get("body") or "").splitlines() if ln.strip()]
        slides.append(_slide_xml(sec.get("title") or "Section", lines or ["No narrative provided."]))
    if charts:
        slides.append(_slide_xml(charts[0].get("title") or "Key Chart", ["Chart-ready metric view from gathered data."], charts[0]))
    if evidence:
        lines = []
        for src in evidence[:8]:
            lines.append((src.get("title") or "Source")[:90])
        slides.append(_slide_xml("Source Notes", lines))
    sld_ids = "".join(f'<p:sldId id="{256+i}" r:id="rId{i+1}"/>' for i in range(len(slides)))
    pres_xml = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:sldSz cx="{SLIDE_W}" cy="{SLIDE_H}" type="wide"/><p:sldIdLst>{sld_ids}</p:sldIdLst></p:presentation>'
    rels = ''.join(f'<Relationship Id="rId{i+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i+1}.xml"/>' for i in range(len(slides)))
    overrides = ''.join(f'<Override PartName="/ppt/slides/slide{i+1}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>' for i in range(len(slides)))
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>{overrides}</Types>')
        zf.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/></Relationships>')
        zf.writestr("ppt/_rels/presentation.xml.rels", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>')
        zf.writestr("ppt/presentation.xml", pres_xml)
        for idx, slide in enumerate(slides, 1):
            zf.writestr(f"ppt/slides/slide{idx}.xml", slide)


def _pdf_escape(text: str) -> str:
    return str(text or "").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _write_pdf(path: Path, title: str, sections: List[Dict[str, str]], records: List[Dict[str, Any]], charts: List[Dict[str, Any]]) -> None:
    lines = [title, ""]
    for sec in sections:
        lines.append(sec.get("title") or "Section")
        lines.extend([ln.strip() for ln in str(sec.get("body") or "").splitlines() if ln.strip()][:8])
        lines.append("")
    if records:
        lines.append("Data snapshot")
        headers = list(records[0].keys())[:5]
        lines.append(" | ".join(headers))
        for row in records[:10]:
            lines.append(" | ".join(str(row.get(h, ""))[:18] for h in headers))
    stream = ["BT /F1 22 Tf 50 760 Td (" + _pdf_escape(lines[0][:80]) + ") Tj ET"]
    y = 725
    for line in lines[1:55]:
        size = 13 if line and not line.endswith(":" ) else 12
        stream.append(f"BT /F1 {size} Tf 50 {y} Td ({_pdf_escape(line[:105])}) Tj ET")
        y -= 18
        if y < 60:
            break
    if charts:
        chart = charts[0]
        labels = chart.get("labels") or chart.get("x") or chart.get("categories") or []
        vals = chart.get("values") or []
        nums = [_num(v) or 0 for v in vals]
        if labels and nums:
            maxv = max(max(nums), 1)
            x = 55
            for lab, val in zip(labels[:8], nums[:8]):
                h = 90 * val / maxv
                stream.append(f"0.14 0.39 0.92 rg {x} 75 {26} {h:.2f} re f")
                stream.append(f"BT /F1 7 Tf {x-5} 62 Td ({_pdf_escape(str(lab)[:8])}) Tj ET")
                x += 44
    content = "\n".join(stream).encode("latin-1", errors="replace")
    objects = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream")
    out = [b"%PDF-1.4\n"]
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(sum(len(x) for x in out))
        out.append(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = sum(len(x) for x in out)
    out.append(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for off in offsets[1:]:
        out.append(f"{off:010d} 00000 n \n".encode())
    out.append(f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    path.write_bytes(b"".join(out))


def _write_csv(path: Path, records: List[Dict[str, Any]]) -> None:
    if not records:
        path.write_text("metric,value\nstatus,no tabular records supplied\n", encoding="utf-8")
        return
    headers = []
    for row in records:
        for key in row.keys():
            if key not in headers:
                headers.append(key)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        for row in records:
            writer.writerow({k: row.get(k, "") for k in headers})


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    title = str(params.get("title") or params.get("report_title") or "Research Data Briefing").strip()
    stem = _safe_name(params.get("name") or title)
    base_dir_raw = str(params.get("output_dir") or "").strip()
    if base_dir_raw:
        out_dir = resolve_path(ctx or {}, {**params, "repo_aware": False}, base_dir_raw)
    else:
        base = resolve_base_dir(ctx or {}, params or {})
        app = (ctx or {}).get("app") if isinstance(ctx, dict) else None
        data_dir = getattr(getattr(app, "state", None), "data_dir", None)
        if data_dir:
            out_dir = Path(str(data_dir)).resolve() / "generated" / "report_packs"
        elif (base / "llmloader2" / "data").is_dir():
            out_dir = base / "llmloader2" / "data" / "generated" / "report_packs"
        elif base.name == "llmloader2" and (base / "data").is_dir():
            out_dir = base / "data" / "generated" / "report_packs"
        else:
            out_dir = base / "data" / "generated" / "report_packs"
    out_dir.mkdir(parents=True, exist_ok=True)
    token = str(params.get("run_id") or int(time.time()))[:12]
    prefix = f"{stem}_{token}"
    sections = _normalize_sections(params)
    records = _normalize_records(params)
    charts = _normalize_charts(params, records)
    evidence = _normalize_evidence(params)
    docx = out_dir / f"{prefix}.docx"
    pptx = out_dir / f"{prefix}.pptx"
    pdf = out_dir / f"{prefix}.pdf"
    csv_path = out_dir / f"{prefix}.csv"
    json_path = out_dir / f"{prefix}.json"
    _write_docx(docx, title, sections, records, evidence)
    _write_pptx(pptx, title, sections, charts, evidence)
    _write_pdf(pdf, title, sections, records, charts)
    _write_csv(csv_path, records)
    json_path.write_text(json.dumps({"title": title, "sections": sections, "records": records, "charts": charts, "evidence": evidence}, ensure_ascii=False, indent=2), encoding="utf-8")
    files = [str(docx), str(pptx), str(pdf), str(csv_path), str(json_path)]
    return {"ok": True, "data": {"files": files, "docx": str(docx), "pptx": str(pptx), "pdf": str(pdf), "csv": str(csv_path), "json": str(json_path), "charts": charts, "record_count": len(records), "source_count": len(evidence)}, "files": files, "warnings": []}


TOOL_SPEC = {
    "id": NAME,
    "category": "document",
    "label": "Document: Research Report Pack",
    "description": "Create a professional research/data report pack with DOCX, PPTX, PDF, CSV, and JSON evidence artifacts from sections, records, charts, and source notes.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "sections": {"type": "array"},
            "records": {"type": "array"},
            "charts": {"type": "array"},
            "evidence": {"type": "array"},
            "sources": {"type": "array"},
            "output_dir": {"type": "string"},
            "run_id": {"type": "string"},
        },
        "additionalProperties": True,
    },
}
