from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def write_broll_inspector(
    montage_plan: dict[str, Any], quality_report: dict[str, Any], rendered_frame_qc: dict[str, Any], output: Path,
) -> Path:
    """Write a small, dependency-free inspector for semantic B-roll decisions."""
    output.parent.mkdir(parents=True, exist_ok=True)
    events = [item for item in montage_plan.get("broll", []) if item.get("enabled", True)]
    requests = montage_plan.get("brollRequests", [])
    previews = {
        round(float(item.get("time", 0)), 1): item.get("preview")
        for item in rendered_frame_qc.get("samples", [])
        if item.get("reason") == "broll_active" and item.get("preview")
    }
    cards: list[str] = []
    for event in events:
        start, end = float(event.get("from", 0)), float(event.get("to", 0))
        diagnostics = event.get("selectionDiagnostics", {})
        image = previews.get(round(start + (end - start) * 0.5, 1))
        image_html = f'<img src="{Path(image).resolve().as_uri()}" alt="B-roll preview">' if image else ""
        assets = ", ".join(str(shot.get("file", "")) for shot in event.get("shots", []))
        cards.append(
            '<article class="card">' + image_html
            + f'<h3>{start:.2f}–{end:.2f}s · relevance {float(diagnostics.get("localRelevance", 0)):.2f}</h3>'
            + f'<p>{html.escape(str(event.get("reason", "")))}</p><code>{html.escape(assets)}</code></article>'
        )
    rejected_rows = "".join(
        "<tr>"
        f"<td>{float(item.get('time', 0)):.2f}</td><td>{html.escape(str(item.get('status', '')))}</td>"
        f"<td>{float(item.get('brollNecessity', {}).get('local_semantic_relevance', 0) or 0):.2f}</td>"
        f"<td>{html.escape(str(item.get('text', '')))}</td>"
        f"<td>{html.escape(str((item.get('assetCandidate') or {}).get('file', '—')))}</td></tr>"
        for item in requests if item.get("status") != "MATCHED"
    )
    metrics = quality_report.get("metrics", {}).get("visual_penalties", {})
    payload = html.escape(json.dumps(metrics, ensure_ascii=False, indent=2))
    document = f"""<!doctype html><html lang="ru"><meta charset="utf-8"><title>ShortsAI B-roll Inspector</title>
<style>body{{font:15px system-ui;background:#111;color:#eee;margin:32px}}h1,h2{{margin:18px 0}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}}.card{{background:#1d1d1d;border:1px solid #333;border-radius:14px;padding:14px}}img{{width:100%;aspect-ratio:9/16;object-fit:cover;border-radius:9px}}code,pre{{white-space:pre-wrap;color:#ffd75a}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #333;padding:8px;text-align:left}}</style>
<body><h1>Semantic B-roll Inspector</h1><p>Executed: {len(events)} · Rejected: {sum(item.get('status') != 'MATCHED' for item in requests)}</p>
<h2>Executed inserts</h2><div class="grid">{''.join(cards) or '<p>No B-roll was executed: speaker-only was preferred.</p>'}</div>
<h2>Rejected candidates</h2><table><thead><tr><th>Time</th><th>Decision</th><th>Relevance</th><th>Local phrase</th><th>Best asset</th></tr></thead><tbody>{rejected_rows}</tbody></table>
<h2>QC metrics</h2><pre>{payload}</pre></body></html>"""
    output.write_text(document, encoding="utf-8")
    return output
