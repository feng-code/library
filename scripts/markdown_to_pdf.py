#!/usr/bin/env python3
"""Small dependency-free Markdown-to-PDF renderer for Chinese tutorial docs.

It intentionally renders Markdown as readable formatted text and uses the
standard PDF CJK CID font STSong-Light with UniGB-UCS2-H encoding.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import unicodedata
from pathlib import Path

PAGE_W = 595.28
PAGE_H = 841.89
MARGIN_X = 42
MARGIN_TOP = 46
MARGIN_BOTTOM = 46
BODY_SIZE = 10.5
CODE_SIZE = 9.0
H1_SIZE = 18
H2_SIZE = 15
H3_SIZE = 12.5
LINE_GAP = 4


def visual_width(s: str) -> float:
    total = 0.0
    for ch in s:
        if ch == '\t':
            total += 4
        elif unicodedata.east_asian_width(ch) in {'F', 'W'}:
            total += 2
        else:
            total += 1
    return total


def wrap_line(line: str, max_cols: int) -> list[str]:
    if line == '':
        return ['']
    out: list[str] = []
    current = ''
    width = 0.0
    for ch in line:
        ch_w = 4 if ch == '\t' else 2 if unicodedata.east_asian_width(ch) in {'F', 'W'} else 1
        if width + ch_w > max_cols and current:
            out.append(current.rstrip())
            current = ch
            width = ch_w
        else:
            current += ch
            width += ch_w
    if current or not out:
        out.append(current.rstrip())
    return out


def text_to_hex(s: str) -> str:
    return s.encode('utf-16-be', errors='replace').hex().upper()


def pdf_escape_text_command(text: str, x: float, y: float, font_size: float, font='F1') -> str:
    return f"BT /{font} {font_size:.2f} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm <{text_to_hex(text)}> Tj ET\n"


def parse_markdown(md: str) -> list[tuple[str, float, float, bool]]:
    """Return entries of (text, font_size, extra_before, is_code)."""
    entries: list[tuple[str, float, float, bool]] = []
    in_code = False
    for raw in md.splitlines():
        line = raw.rstrip('\n')
        if line.startswith('```'):
            in_code = not in_code
            entries.append(('', CODE_SIZE, 2, True))
            continue
        if in_code:
            entries.append((line, CODE_SIZE, 0, True))
            continue
        if line.strip() == '---':
            entries.append(('─' * 45, BODY_SIZE, 4, False))
            continue
        m = re.match(r'^(#{1,6})\s+(.*)$', line)
        if m:
            level = len(m.group(1))
            text = m.group(2)
            size = H1_SIZE if level == 1 else H2_SIZE if level == 2 else H3_SIZE
            entries.append((text, size, 10 if level <= 2 else 7, False))
            continue
        if line.startswith('> '):
            entries.append(('引言：' + line[2:], BODY_SIZE, 2, False))
            continue
        entries.append((line, BODY_SIZE, 0, False))
    return entries


class PdfWriter:
    def __init__(self):
        self.objects: list[bytes] = []

    def add(self, data: str | bytes) -> int:
        if isinstance(data, str):
            data = data.encode('latin1')
        self.objects.append(data)
        return len(self.objects)

    def build(self, root_obj: int) -> bytes:
        out = bytearray(b'%PDF-1.4\n%\xE2\xE3\xCF\xD3\n')
        offsets = [0]
        for i, obj in enumerate(self.objects, 1):
            offsets.append(len(out))
            out += f'{i} 0 obj\n'.encode('ascii')
            out += obj
            out += b'\nendobj\n'
        xref_pos = len(out)
        out += f'xref\n0 {len(self.objects) + 1}\n'.encode('ascii')
        out += b'0000000000 65535 f \n'
        for off in offsets[1:]:
            out += f'{off:010d} 00000 n \n'.encode('ascii')
        out += f'trailer << /Size {len(self.objects) + 1} /Root {root_obj} 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n'.encode('ascii')
        return bytes(out)


def render_pdf(md_path: Path, pdf_path: Path) -> None:
    md = md_path.read_text(encoding='utf-8')
    entries = parse_markdown(md)

    pages: list[str] = []
    current: list[str] = []
    y = PAGE_H - MARGIN_TOP
    page_no = 1

    def new_page():
        nonlocal current, y, page_no
        # footer
        current.append(pdf_escape_text_command(f'第 {page_no} 页', PAGE_W / 2 - 20, 24, 8.5))
        pages.append(''.join(current))
        current = []
        y = PAGE_H - MARGIN_TOP
        page_no += 1

    # cover meta header on first page
    current.append(pdf_escape_text_command('RTOS 项目多任务设计教程', MARGIN_X, y, 20))
    y -= 28
    current.append(pdf_escape_text_command(f'生成日期：{dt.date.today().isoformat()}', MARGIN_X, y, 10))
    y -= 24

    for text, size, extra_before, is_code in entries:
        y -= extra_before
        max_cols = 76 if is_code else max(28, int((PAGE_W - 2 * MARGIN_X) / (size * 0.52)))
        prefix = ''
        # Preserve Markdown bullets/tables as text; indent code blocks.
        lines = wrap_line(text, max_cols)
        for i, wrapped in enumerate(lines):
            line = ('    ' + wrapped) if is_code and wrapped else wrapped
            line_height = size + LINE_GAP
            if y - line_height < MARGIN_BOTTOM:
                new_page()
            current.append(pdf_escape_text_command(line, MARGIN_X, y, size))
            y -= line_height
        if text == '':
            y -= size * 0.35

    if current:
        current.append(pdf_escape_text_command(f'第 {page_no} 页', PAGE_W / 2 - 20, 24, 8.5))
        pages.append(''.join(current))

    pdf = PdfWriter()
    # Font objects using standard Simplified Chinese CID font.
    cid_font = pdf.add('<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light /CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 2 >> /DW 1000 >>')
    font = pdf.add(f'<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light /Encoding /UniGB-UCS2-H /DescendantFonts [{cid_font} 0 R] >>')

    page_objs = []
    content_objs = []
    for content in pages:
        stream = content.encode('ascii')
        content_obj = pdf.add(b'<< /Length ' + str(len(stream)).encode('ascii') + b' >>\nstream\n' + stream + b'endstream')
        content_objs.append(content_obj)
        page_obj = pdf.add('')
        page_objs.append(page_obj)

    pages_obj = pdf.add('')
    catalog_obj = pdf.add(f'<< /Type /Catalog /Pages {pages_obj} 0 R >>')

    for idx, page_obj in enumerate(page_objs):
        page_dict = (
            f'<< /Type /Page /Parent {pages_obj} 0 R '
            f'/MediaBox [0 0 {PAGE_W:.2f} {PAGE_H:.2f}] '
            f'/Resources << /Font << /F1 {font} 0 R >> >> '
            f'/Contents {content_objs[idx]} 0 R >>'
        )
        pdf.objects[page_obj - 1] = page_dict.encode('latin1')

    kids = ' '.join(f'{p} 0 R' for p in page_objs)
    pdf.objects[pages_obj - 1] = f'<< /Type /Pages /Kids [{kids}] /Count {len(page_objs)} >>'.encode('latin1')

    pdf_path.write_bytes(pdf.build(catalog_obj))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('markdown', type=Path)
    parser.add_argument('pdf', type=Path)
    args = parser.parse_args()
    render_pdf(args.markdown, args.pdf)


if __name__ == '__main__':
    main()
