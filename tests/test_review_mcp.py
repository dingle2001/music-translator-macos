import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional MCP SDK is not installed')
class ReviewMCPTest(unittest.TestCase):
    def test_old_report_with_relative_source_paths(self):
        from core.omr.review_mcp import review_score_page

        fixtures = Path(__file__).resolve().parent / 'fixtures'
        pdf = fixtures / 'sheng.pdf'
        xml = fixtures / 'sheng_original.musicxml'
        report = {
            'source_pdf': os.path.relpath(pdf),
            'source_pdf_sha256': hashlib.sha256(pdf.read_bytes()).hexdigest(),
            'source_musicxml': os.path.relpath(xml),
            'source_musicxml_sha256': hashlib.sha256(xml.read_bytes()).hexdigest(),
            'rows': [],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'score.insitu.report.json'
            path.write_text(json.dumps(report), encoding='utf-8')
            image, evidence = review_score_page(2, report_path=str(path))
            self.assertEqual(image.to_image_content().mimeType, 'image/png')
            self.assertIn('"原谱页码": 2', evidence)
            self.assertIn('<measure ', evidence)

            report['source_musicxml_sha256'] = 'stale'
            path.write_text(json.dumps(report), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '不匹配'):
                review_score_page(2, report_path=str(path))
