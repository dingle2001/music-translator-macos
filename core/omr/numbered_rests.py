"""Reconcile numbered rest symbols with MusicXML using source page and row boundaries."""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
import xml.etree.ElementTree as ET

import pymupdf

from core.notation.musicxml_wedges import read_musicxml_bytes
from insitu.pdf_structure import extract_staves, measure_numbers, staff_barlines
from .multirest_collapse import _absorb_attributes, _read_state
from .vector_tempos import _page_marks, printed_rest_strokes, printed_rest_info


def _xml_break(measure, name):
    return any(mark.get(name) == 'yes' for mark in measure.findall('print'))


def _split(measures, *, by_page=False):
    groups = []
    for i, measure in enumerate(measures):
        if not groups or _xml_break(measure, 'new-page') or (
                not by_page and _xml_break(measure, 'new-system')):
            groups.append([])
        groups[-1].append((i, measure))
    return groups


def _full_rest(measure):
    if measure.get('implicit') == 'yes':
        return False
    notes = measure.findall('note')
    if len(notes) != 1 or measure.find('backup') is not None or measure.find('forward') is not None:
        return False
    rest = notes[0].find('rest')
    return (rest is not None and rest.get('measure') == 'yes'
            and notes[0].find('duration') is not None
            and notes[0].find('grace') is None)


def _pitched_cell(measure):
    return any(n.find('pitch') is not None or n.find('unpitched') is not None
               for n in measure.findall('note'))


def _empty_rest_cell(measure):
    # Homr can emit a layout-only measure for a drawn long rest.
    return (measure.get('implicit') != 'yes'
            and all(child.tag in {'print', 'attributes', 'direction', 'barline'} for child in measure))


def _bare_rest(measure):
    return (_full_rest(measure) and all(child.tag == 'note' for child in measure)
            and all(child.tag in {'rest', 'duration', 'type', 'voice', 'staff'} for child in measure[0]))


def _rest_style(measure):
    marks = measure.findall('attributes/measure-style/multiple-rest')
    if not marks:
        return None
    text = (marks[0].text or '').strip()
    return (int(text) if len(text) <= 3 and text.isascii() and text.isdigit()
            and len(marks) == 1 and 2 <= int(text) <= 999 else 0)


def _matching_line(block, slots, *, recognize):
    """Count up to two complete mappings. Apply a repair only if it is unique."""
    measures = [m for _, m in block]

    @lru_cache(maxsize=None)
    def search(slot, index):
        if slot == len(slots):
            return ((),) if index == len(measures) else ()
        count, heads = slots[slot]
        ordinary = index < len(measures) and (not heads or _pitched_cell(measures[index]))
        if count is None:
            lengths = (1,) if ordinary else ()
        else:
            lengths = [0]
            if index < len(measures) and (_full_rest(measures[index]) or _empty_rest_cell(measures[index])
                                          or (recognize and not _pitched_cell(measures[index]))):
                style = _rest_style(measures[index])
                if style in (None, count) or recognize:
                    lengths.append(1)
                    if (_full_rest(measures[index]) and index + count <= len(measures)
                            and all(_bare_rest(m) for m in measures[index + 1:index + count])):
                        lengths.append(count)
                    if recognize:
                        max_k = min(count, len(measures) - index)
                        for k in range(2, max_k + 1):
                            if k in lengths:
                                continue
                            if all((_full_rest(m) or _empty_rest_cell(m) or not _pitched_cell(m))
                                   for m in measures[index + 1:index + k]):
                                lengths.append(k)
                            else:
                                break
        paths = []
        for length in lengths:
            for tail in search(slot + 1, index + length):
                paths.append((length, *tail))
                if len(paths) == 2:
                    return tuple(paths)
        return tuple(paths)

    # Normal case. A source line already matching cell-for-cell should not
    # be reinterpreted as a mixture of missing and expanded rest groups.
    if len(measures) == len(slots) and all(
            (_full_rest(m) or _empty_rest_cell(m) or (recognize and not _pitched_cell(m))) if count else
            (not heads or _pitched_cell(m)) for m, (count, heads) in zip(measures, slots)):
        return (1,) * len(slots)
    if len(slots) > 100:
        return None
    if not any(heads for _, heads in slots) and len(slots) > 1:
        # Without font-verified heads, only repair a row with a surviving
        # pitched anchor. The numbered symbol still fixes its own cell.
        if not any(_pitched_cell(m) for m in measures):
            return None
    paths = search(0, 0)
    return paths[0] if len(paths) == 1 else None


def _whole_rest(number, state):
    divisions, beats, beat_type = state
    duration = Fraction(divisions * beats * 4, beat_type)
    if duration.denominator != 1 or duration <= 0:
        return None
    measure = ET.Element('measure', {'number': number})
    note = ET.SubElement(measure, 'note')
    ET.SubElement(note, 'rest', {'measure': 'yes'})
    ET.SubElement(note, 'duration').text = str(duration.numerator)
    return measure


def _remove_rest_style(measure):
    for attributes in measure.findall('attributes'):
        for style in list(attributes.findall('measure-style')):
            for mark in list(style.findall('multiple-rest')):
                style.remove(mark)
            if not len(style):
                attributes.remove(style)


def _prepare_line(block, slots, states, *, recognize):
    lengths = _matching_line(block, slots, recognize=recognize)
    if lengths is None:
        return None
    measures, counts, actions = [], {}, []
    cursor = 0
    for slot, (take, (count, _)) in enumerate(zip(lengths, slots), 1):
        index, original = block[min(cursor, len(block) - 1)]
        if take:
            measure = original
        else:
            state = states[index] if index else states[1]
            if cursor == len(block):
                state = states[index + 1]
            label = original.get('number', str(index + 1))
            measure = _whole_rest(f'{label}-rest-{slot}', state)
            if measure is None:
                return None
        if count:
            empty = take == 1 and _empty_rest_cell(measure)
            non_full_rest = take >= 1 and recognize and not _full_rest(measure) and not _pitched_cell(measure)
            declared = _rest_style(measure)
            conflict = declared not in (None, count)
            if conflict and not recognize:
                actions.append((slot, ('count_conflict_review', declared)))
                measures.append(measure)
                cursor += take
                continue
            if take != 1 or empty or non_full_rest or declared is not None:
                measure = deepcopy(measure)
                if take > 1:
                    for _, victim in block[cursor + 1:cursor + take]:
                        _absorb_attributes(measure, deepcopy(victim))
                if empty or non_full_rest:
                    inferred = _whole_rest(measure.get('number', str(index + 1)), states[index + 1])
                    if inferred is None:
                        return None
                    for old_note in list(measure.findall('note')):
                        measure.remove(old_note)
                    barline = measure.find("barline[@location='right']")
                    at = list(measure).index(barline) if barline is not None else len(measure)
                    measure.insert(at, inferred[0])
                # This XML is for one-box-per-cell alignment. The number is
                # recorded with its source position and used during export.
                _remove_rest_style(measure)
            if not take:
                if index == 0 and not cursor:
                    for attrs in reversed(original.findall('attributes')):
                        measure.insert(0, deepcopy(attrs))
                    _remove_rest_style(measure)
            status = ('rest_inserted' if not take else 'omr_count_corrected' if conflict else
                      'empty_cell_completed' if empty else 'expanded_rest_collapsed' if take > 1 else
                      'count_confirmed')
            actions.append((slot, (status, declared)))
            counts[slot] = count
        measures.append(measure)
        cursor += take
    if lengths[0] == 0:
        original = block[0][1]
        printed = original.findall('print')
        if printed:
            at = next(i for i, take in enumerate(lengths) if take)
            measures[at] = deepcopy(measures[at])
            for mark in measures[at].findall('print'):
                measures[at].remove(mark)
            for mark in reversed(printed):
                measures[0].insert(0, deepcopy(mark))
    return measures, counts, actions


def reconcile_pdf_numbered_rests(pdf_path: Path, xml_path: Path, *, recognize=False):
    """Return a compact derived tree and local evidence. Never write inputs."""
    root = ET.fromstring(read_musicxml_bytes(xml_path))
    parts = root.findall('part')
    if len(parts) != 1 or any(t.text and t.text.strip() != '1' for t in root.findall('.//attributes/staves')):
        return root, {}, [], False
    part = parts[0]
    original = part.findall('measure')
    pages = _split(original, by_page=True)
    state = (1, 4, 4)
    states = [state]
    for measure in original:
        state = tuple(new if new is not None else old for new, old in zip(_read_state(measure), state))
        states.append(state)

    evidence, counts, result = [], {}, []
    with pymupdf.open(pdf_path) as doc:
        page_count = len(doc)
        for page_index, page in enumerate(doc):
            staves = extract_staves(page, page_index + 1)
            if not staves:
                if len(pages) == page_count:
                    result.extend(m for _, m in pages[page_index])
                continue
            _, heads, numbers = _page_marks(page)
            drawings = page.get_drawings()
            blocks = (_split([m for _, m in pages[page_index]])
                      if len(pages) == page_count else [])
            offset = pages[page_index][0][0] if blocks else 0
            reliable = len(blocks) == len(staves)
            for line, staff in enumerate(staves, 1):
                edges = [staff.x0, *staff_barlines(page, staff)]
                slots, marks = [], []
                for cell, (left, right) in enumerate(zip(edges, edges[1:]), 1):
                    strokes = printed_rest_strokes(drawings, staff, left, right, require_caps=True)
                    mark = printed_rest_info(strokes, staff, numbers)
                    observed = any(left <= x < right and staff.top - 6 * staff.line_spacing <= y
                                   <= staff.bottom + 6 * staff.line_spacing
                                   and 2.4 * staff.line_spacing <= size <= 4.6 * staff.line_spacing
                                   for x, y, size in heads)
                    slots.append((mark[1] if mark and not observed else None, observed))
                    if strokes:
                        marks.append({'page': page_index + 1, 'line': line, 'cell': cell,
                                      'bounds_points': [round(v, 2) for v in (left, staff.top, right, staff.bottom)],
                                      'printed_rest_measures': mark[1] if mark else None,
                                      'status': ('number_or_stroke_ambiguous' if mark is None else
                                                 'conflicting_noteheads' if observed else 'needs_review')})
                if marks:
                    first_printed = measure_numbers(page, staff)
                    if first_printed is not None:
                        for mark in marks:
                            mark['printed_line_start'] = first_printed
                if not reliable:
                    evidence.extend(marks)
                    continue
                block = [(offset + i, m) for i, m in blocks[line - 1]]
                known = any(count for count, _ in slots)
                prepared = (_prepare_line(block, slots, states, recognize=recognize)
                            if known and (len(block) == len(slots) or
                                          all(mark['status'] == 'needs_review' for mark in marks)) else None)
                if prepared:
                    repaired, by_slot, actions = prepared
                    counts.update({len(result) + cell: count for cell, count in by_slot.items()})
                    actions = dict(actions)
                    for mark in marks:
                        cell = mark['cell']
                        if cell in actions:
                            mark['status'], declared = actions[cell]
                            if declared:
                                mark['declared_rest_measures'] = declared
                        if cell in by_slot:
                            mark['musicxml_index'] = len(result) + cell
                            mark['musicxml_measure_number'] = repaired[cell - 1].get('number')
                    result.extend(repaired)
                else:
                    result.extend(m for _, m in block)
                evidence.extend(marks)
            if not reliable and len(pages) == page_count:
                result.extend(m for _, m in pages[page_index])
    if len(pages) != page_count or not counts:
        return root, {}, evidence, False
    changed = result != original
    if changed:
        # Replace only measure elements and retain the original sequence of
        # non-measure data in the document header.
        for measure in original:
            part.remove(measure)
        part.extend(result)
    return root, counts, evidence, changed
