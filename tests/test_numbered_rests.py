"""A printed long rest has one engraved cell and several playback bars."""
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

import pymupdf
from music21 import converter

from core.notation.jianpu import build_jianpu_ly_text
from core.omr.numbered_rests import reconcile_pdf_numbered_rests
from core.render.renderer import _expand_compact_rests_for_midi
from core.omr.homr_runner import _merge_homr_musicxml_pages


_HEADER = """<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Flute</part-name>
</score-part></part-list><part id="P1">"""
_STATE = '<attributes><divisions>4</divisions><time><beats>5</beats><beat-type>4</beat-type></time></attributes>'
_REST = '<note><rest measure="yes"/><duration>20</duration></note>'
_PITCHED = '<note><pitch><step>C</step><octave>4</octave></pitch><duration>20</duration></note>'


def _xml(path, contents):
    path.write_text(_HEADER + contents + '</part></score-partwise>', encoding='utf-8')
    return path


def _pdf(path, *, caps=True, label='3'):
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=600, height=320)
        for y in (100, 105, 110, 115, 120):
            page.draw_line((40, y), (540, y), width=.5)
        for x in (290, 540):
            page.draw_line((x, 100), (x, 120), width=.5)
        page.draw_line((115, 110), (205, 110), width=2.5)
        if caps:
            for x in (115, 205):
                page.draw_line((x, 105), (x, 115), width=.75)
        if label:
            page.insert_text((156, 94), label, fontsize=10)
        pdf.save(path)
    return path


class NumberedRestTest(unittest.TestCase):
    def test_missing_rest_is_inserted_as_one_cell_with_the_current_meter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = _pdf(root / 'input.pdf')
            xml = _xml(root / 'input.musicxml', f'<measure number="7">{_STATE}{_PITCHED}</measure>')
            before = xml.read_bytes()
            score, counts, evidence, changed = reconcile_pdf_numbered_rests(pdf, xml)
            measures = score.findall('part/measure')
            self.assertTrue(changed)
            self.assertEqual(counts, {1: 3})
            self.assertEqual(evidence[0]['status'], 'rest_inserted')
            self.assertEqual(measures[0].findtext('note/duration'), '20')
            self.assertEqual(measures[1].get('number'), '7')
            self.assertEqual(ET.tostring(measures[1].find('note')), ET.tostring(ET.fromstring(_PITCHED)))
            self.assertEqual(xml.read_bytes(), before)

            parsed = converter.parseData(ET.tostring(score, encoding='unicode'), format='musicxml')
            text = build_jianpu_ly_text(parsed, '', multirest_counts=counts)
            self.assertIn('R*3', text)
            _expand_compact_rests_for_midi(parsed, counts)
            part = parsed.parts[0]
            event = next(iter(part.recurse().notes))
            self.assertEqual(event.getOffsetInHierarchy(part), 15)

    def test_expanded_xml_stays_unchanged_on_disk_and_collapses_to_one_cell(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = _pdf(root / 'input.pdf')
            style = '<measure-style><multiple-rest>3</multiple-rest></measure-style>'
            xml = _xml(root / 'input.musicxml',
                       f'<measure number="1">{_STATE.replace("</attributes>", style + "</attributes>")}{_REST}</measure>'
                       f'<measure number="2">{_REST}</measure><measure number="3">{_REST}</measure>'
                       f'<measure number="4">{_PITCHED}</measure>')
            before = xml.read_bytes()
            text = build_jianpu_ly_text(converter.parse(xml), '')
            self.assertIn('R*3', text)
            tree, counts, evidence, changed = reconcile_pdf_numbered_rests(pdf, xml)
            self.assertTrue(changed)
            self.assertEqual(counts, {1: 3})
            self.assertEqual(evidence[0]['status'], 'expanded_rest_collapsed')
            self.assertEqual(len(tree.findall('part/measure')), 2)
            self.assertEqual(xml.read_bytes(), before)

    def test_fresh_omr_conflict_on_empty_cell_uses_source_but_user_xml_goes_to_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = _pdf(root / 'input.pdf', label='13')
            style = '<measure-style><multiple-rest>8</multiple-rest></measure-style>'
            xml = _xml(root / 'input.musicxml',
                       f'<measure number="1">{_STATE.replace("</attributes>", style + "</attributes>")}</measure>'
                       f'<measure number="2">{_PITCHED}</measure>')
            _, counts, report, changed = reconcile_pdf_numbered_rests(pdf, xml)
            self.assertFalse(changed)
            self.assertEqual(counts, {})
            self.assertEqual(report[0]['status'], 'count_conflict_review')
            _, counts, report, changed = reconcile_pdf_numbered_rests(pdf, xml, recognize=True)
            self.assertTrue(changed)
            self.assertEqual(counts, {1: 13})
            self.assertEqual(report[0]['status'], 'omr_count_corrected')
            self.assertEqual(report[0]['declared_rest_measures'], 8)

    def test_uncorroborated_stroke_cannot_insert_a_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            xml = _xml(root / 'input.musicxml', f'<measure number="7">{_STATE}{_PITCHED}</measure>')
            for index, (caps, label) in enumerate(((True, ''), (False, '3'))):
                with self.subTest(caps=caps):
                    pdf = _pdf(root / f'input{index}.pdf', caps=caps, label=label)
                    _, counts, _, changed = reconcile_pdf_numbered_rests(pdf, xml, recognize=True)
                    self.assertFalse(changed)
                    self.assertEqual(counts, {})

    def test_homr_page_merge_preserves_both_page_and_system_breaks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page1 = _xml(root / 'a.musicxml', f'<measure number="1">{_STATE}{_PITCHED}</measure>')
            page2 = _xml(root / 'b.musicxml',
                         f'<measure number="1"><print new-system="yes"/>{_PITCHED}</measure>')
            combined = root / 'combined.musicxml'
            self.assertTrue(_merge_homr_musicxml_pages([page1, page2], combined))
            breaks = ET.parse(combined).findall('part/measure/print')
            self.assertEqual(breaks[0].attrib, {'new-page': 'yes', 'new-system': 'yes'})


if __name__ == '__main__':
    unittest.main()
