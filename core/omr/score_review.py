"""Prepare score images and matching MusicXML for read-only review."""
from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

import pymupdf

from core.notation.musicxml_wedges import read_musicxml_bytes


CONTEXT_TAGS = ('divisions', 'key', 'time', 'clef', 'measure-style')
NOTE_TAGS = {'grace', 'chord', 'pitch', 'unpitched', 'rest', 'duration', 'tie', 'voice',
             'type', 'dot', 'accidental', 'time-modification', 'staff', 'beam', 'notations'}


class ScoreReviewError(RuntimeError):
    """The requested score evidence could not be prepared."""


def _page_context(pdf: Path, musicxml: Path, page: int, page_count: int):
    root = ET.fromstring(read_musicxml_bytes(musicxml))
    for element in root.iter():
        element.tag = element.tag.rsplit('}', 1)[-1]
        if element.text and not element.text.strip():
            element.text = None
        if element.tail and not element.tail.strip():
            element.tail = None
    parts = root.findall('part')
    if root.tag != 'score-partwise' or len(parts) != 1:
        raise ScoreReviewError('目前校谱支持只有一个 part 的 MusicXML 分谱。')
    measures = parts[0].findall('measure')
    if not measures:
        raise ScoreReviewError('MusicXML 中没有可校对的小节。')

    starts = [0, *(index for index, measure in enumerate(measures[1:], 1)
                   if measure.find("print[@new-page='yes']") is not None)]
    if len(starts) == page_count:
        starts.append(len(measures))
        systems = [(starts[page - 1], starts[page])]
        alignment = 'MusicXML 分页'
    else:
        from insitu.align import align_from_files

        layouts, slices = align_from_files(pdf, musicxml)
        systems = [(sl.omr_start, sl.omr_end) for layout, sl in zip(layouts, slices)
                   if layout.staff.page == page and sl.omr_start < sl.omr_end]
        alignment = 'PDF 谱表与 MusicXML 小节数推定，可能错位'
    if not systems:
        raise ScoreReviewError('无法把这一页对齐到 MusicXML。请使用与 PDF 分页匹配的 MusicXML。')

    excerpt = ET.Element('review', page=str(page), alignment=alignment)
    context = ET.SubElement(excerpt, 'inherited-attributes')
    inherited = {}
    for measure in measures[:systems[0][0]]:
        for attributes in measure.findall('attributes'):
            for item in attributes:
                if item.tag in CONTEXT_TAGS:
                    inherited[item.tag, item.get('number')] = item
    context.extend(inherited.values())
    labels = {}
    for start, end in systems:
        group = ET.SubElement(excerpt, 'measure-range')
        for index in range(start, end):
            measure = measures[index]
            label = measure.get('number', str(index + 1))
            labels[index + 1] = label
            item = ET.SubElement(group, 'measure', index=str(index + 1), number=label)
            item.tail = '\n'
            for event in measure:
                if event.tag == 'attributes':
                    ET.SubElement(item, 'attributes').extend(
                        child for child in event if child.tag in CONTEXT_TAGS)
                elif event.tag == 'note':
                    ET.SubElement(item, 'note').extend(child for child in event if child.tag in NOTE_TAGS)
                elif event.tag in {'backup', 'forward', 'barline'}:
                    item.append(event)
    return ET.tostring(excerpt, encoding='unicode'), labels, alignment


def prepare_page(pdf: Path, musicxml: Path, page: int) -> tuple[bytes, str, dict[int, str], str]:
    with pymupdf.open(pdf) as doc:
        if not 1 <= page <= len(doc):
            raise ScoreReviewError(f'PDF 页码必须在 1 至 {len(doc)} 之间。')
        try:
            excerpt, labels, alignment = _page_context(pdf, musicxml, page, len(doc))
        except (ET.ParseError, zipfile.BadZipFile, KeyError) as exc:
            raise ScoreReviewError('无法读取用于校谱的 MusicXML。') from exc
        source_page = doc[page - 1]
        scale = min(3.0, 2800 / max(source_page.rect.width, source_page.rect.height))
        image = source_page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes('png')
    return image, excerpt, labels, alignment
