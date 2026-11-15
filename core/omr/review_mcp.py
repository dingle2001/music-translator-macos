"""Read-only score evidence over local MCP stdio."""
from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import json
from pathlib import Path
import sys

from mcp.server.fastmcp import FastMCP, Image
from mcp.types import ToolAnnotations

from core.omr.score_review import prepare_page


server = FastMCP(
    'Music Translator',
    instructions='校对五线谱时，请把原谱图、MusicXML 与本地告警相互印证。按原谱页码和谱行定位，'
                 '并区分印刷小节编号与 MusicXML 顺序索引。证据不足时标明待核对，勿直接修改乐谱。',
)


def _read_path(value: str | None, suffixes: set[str], *, report_entry: bool = False) -> Path:
    path = Path(value or '').expanduser()
    if report_entry and value:
        path = path.resolve()
    if not path.is_absolute() or path.suffix.lower() not in suffixes or not path.is_file():
        if report_entry:
            raise ValueError('找不到报告记录的源文件，请同时提供原 PDF 和源调 MusicXML 的绝对路径。')
        raise ValueError(f'请提供存在的绝对文件路径，支持 {", ".join(sorted(suffixes))}。')
    return path


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
             structured_output=False)
def review_score_page(page: int, pdf_path: str | None = None, musicxml_path: str | None = None,
                      report_path: str | None = None) -> list:
    """读取一页五线谱图、对应的源调 MusicXML 和本地告警。

    page 是从 1 开始的原 PDF 页码。可给 .insitu.report.json 单独定位输入，
    或同时给 pdf_path 和 musicxml_path。也可附上报告以获取逐行疑点。
    """
    report = {}
    if report_path:
        report = json.loads(_read_path(report_path, {'.json'}).read_text(encoding='utf-8'))
        if not isinstance(report, dict) or not isinstance(report.get('rows'), list):
            raise ValueError('请提供转换生成的 .insitu.report.json。')
    if bool(pdf_path) != bool(musicxml_path):
        raise ValueError('请同时提供原 PDF 和 MusicXML，或仅提供原位报告。')
    pdf = _read_path(pdf_path or report.get('source_pdf'), {'.pdf'}, report_entry=pdf_path is None)
    musicxml = _read_path(musicxml_path or report.get('source_musicxml'), {'.xml', '.musicxml', '.mxl'},
                          report_entry=musicxml_path is None)
    if report:
        for path, field in ((pdf, 'source_pdf_sha256'), (musicxml, 'source_musicxml_sha256')):
            with path.open('rb') as source:
                actual = hashlib.file_digest(source, 'sha256').hexdigest()
            if actual != report.get(field):
                raise ValueError('原位报告与原谱或 MusicXML 不匹配，请使用同次转换的文件，或省略报告。')
        if '.transposed-' in musicxml.name:
            raise ValueError('此原位报告使用了移调后的 MusicXML，请改为显式提供原谱和源调 MusicXML。')

    # The existing aligner prints diagnostics. Keep stdout reserved for MCP.
    with redirect_stdout(sys.stderr):
        image, excerpt, labels, alignment = prepare_page(pdf, musicxml, page)
    rows = []
    for row in report.get('rows', []):
        if row['page'] != page:
            continue
        start = row['musicxml_start_index']
        rows.append({
            '谱行': row['staff_index'],
            '原图小节数': row['pdf_measures'],
            'MusicXML 小节索引范围': [start + 1, row['musicxml_end_index_exclusive']] if start is not None else None,
            '识谱时值超出的小节索引': sorted({
                start + offset + 1 for voice in row['voices'] for offset in voice['overfilled_measures']
            }) if start is not None else [],
            '延音疑点': [issue for voice in row['voices'] for issue in voice['tie_review_measures']],
        })
    details = {
        '原谱': pdf.name, 'MusicXML': musicxml.name, '原谱页码': page, '小节定位依据': alignment,
        'MusicXML 小节索引范围': [min(labels), max(labels)], '逐行本地证据': rows,
    }
    return [Image(data=image, format='png'), json.dumps(details, ensure_ascii=False, indent=2) + '\n\n' + excerpt]


if __name__ == '__main__':
    server.run(transport='stdio')
