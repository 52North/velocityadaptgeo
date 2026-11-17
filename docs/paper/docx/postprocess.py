"""Second step of `make docx`: rewrite pandoc's output in place so it uses the template's styles.

Usage: python3 docx/postprocess.py build/main.docx main.tex

- paragraph/table styles pandoc names itself -> styles of template/Mustertext_Tagungsband.docx
- captions "Figure 1: text" -> bold "Figure 1:" + tab + text, as in the template
- odd running head: sample text -> \\runningauthors: \\runningtitle from main.tex
- document title/author (docProps/core.xml) from \\hypersetup pdftitle/pdfauthor in main.tex
"""

import re
import sys
import zipfile
from pathlib import Path

# pandoc style id -> template style id (ids are the Word names without spaces/umlauts)
PARAGRAPH_STYLES = {
    "BodyText": "Standard",
    "FirstParagraph": "Standard",
    "Compact": "Standard",
    "ImageCaption": "Abbildungsberschrift",
    "TableCaption": "Tabellenberschrift",
    "CaptionedFigure": "Grafik",
}
# FigureTable (layout table for side-by-side images) is not defined anywhere -> no borders
TABLE_STYLES = {"Table": "Tabellenraster", "FigureTable": "NormaleTabelle"}
# Character styles pandoc references but does not define (heading numbers)
UNDEFINED_RUN_STYLES = ("SectionNumber",)
# Captions stay on the page of their figure/table (LaTeX floats do this in the PDF), headings
# with their text (the template's heading styles lack "keep with next")
KEEP_WITH_NEXT = (
    "Abbildungsberschrift",
    "Tabellenberschrift",
    "berschrift1",
    "berschrift2",
    "berschrift3",
)

# "Figure" + (non-breaking) space run (with pandoc's language rPr), SEQ field, ": text" run
CAPTION = re.compile(
    r'<w:r>(?:<w:rPr>(?P<rpr>.*?)</w:rPr>)?<w:t xml:space="preserve">(?P<label>(?:Figure|Table)[ \xa0])</w:t></w:r>'
    r'<w:fldSimple w:instr="(?P<instr>[^"]*)"><w:r><w:t>(?P<num>\d+)</w:t></w:r></w:fldSimple>'
    r"(?P<bookmark><w:bookmarkEnd [^>]*/>)?"
    r'<w:r>(?P<text_rpr><w:rPr>.*?</w:rPr>)?<w:t xml:space="preserve">: '
)

# Tables as in the sample table: style Tabellenüberschrift in the cells, 9 pt, cell padding
# 0.1 cm, header row shaded with 3 pt before/after, data rows 1 pt (format-spec.md, Tables)
TABLE = re.compile(r'<w:tbl><w:tblPr><w:tblStyle w:val="Tabellenraster" />.*?</w:tbl>', re.DOTALL)
RUN_START = re.compile(r"<w:r>(?:<w:rPr>(.*?)</w:rPr>)?")
CELL_MARGINS = (
    '<w:tblCellMar><w:left w:w="57" w:type="dxa" /><w:right w:w="57" w:type="dxa" /></w:tblCellMar>'
)
HEAD_SHADING = '<w:shd w:val="clear" w:color="auto" w:fill="DDDDDD" />'
SIZE_9PT = '<w:sz w:val="18" /><w:szCs w:val="18" />'


def latex_arg(tex: str, pattern: str) -> str:
    """Plain text of the first match of `pattern` (one group) in main.tex."""
    text = re.search(pattern, tex, re.DOTALL).group(1)
    text = text.replace("\\ ", " ").replace("\\&", "&")
    return re.sub(r"\s+", " ", text).strip()


def xml_text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def bold_run(rpr: str, content: str) -> str:
    return f"<w:r><w:rPr><w:b/>{rpr}</w:rPr>{content}</w:r>"


def fix_caption(m: re.Match) -> str:
    """Bold "Figure 1:" + tab; the SEQ field as a complex field so its number can be bold."""
    rpr = m["rpr"] or ""
    field = "".join(
        bold_run(rpr, content)
        for content in (
            '<w:fldChar w:fldCharType="begin"/>',
            f'<w:instrText xml:space="preserve">{m["instr"]}</w:instrText>',
            '<w:fldChar w:fldCharType="separate"/>',
            f'<w:t>{m["num"]}</w:t>',
            '<w:fldChar w:fldCharType="end"/>',
        )
    )
    return (
        bold_run(rpr, f'<w:t xml:space="preserve">{m["label"]}</w:t>')
        + field
        + (m["bookmark"] or "")
        + bold_run(rpr, "<w:t>:</w:t>")
        + f'<w:r>{m["text_rpr"] or ""}<w:tab/><w:t xml:space="preserve">'
    )


def size_9pt(m: re.Match) -> str:
    rpr = m[1] or ""
    # sz must come before lang in rPr
    rpr = rpr.replace("<w:lang", SIZE_9PT + "<w:lang", 1) if "<w:lang" in rpr else rpr + SIZE_9PT
    return f"<w:r><w:rPr>{rpr}</w:rPr>"


def format_rows(xml: str, space: int) -> str:
    xml = xml.replace(
        '<w:pStyle w:val="Standard" />',
        '<w:pStyle w:val="Tabellenberschrift" />'
        f'<w:spacing w:before="{space}" w:after="{space}" /><w:ind w:left="0" w:firstLine="0" />',
    )
    return RUN_START.sub(size_9pt, xml)


def fix_table(m: re.Match) -> str:
    tbl = m[0].replace("<w:tblLook", CELL_MARGINS + "<w:tblLook", 1)
    head_end = tbl.index("</w:tr>")  # pandoc writes the header row first
    head = format_rows(tbl[:head_end], 60).replace("<w:tcPr />", f"<w:tcPr>{HEAD_SHADING}</w:tcPr>")
    return head + format_rows(tbl[head_end:], 20)


def fix_document(xml: str) -> str:
    for old, new in PARAGRAPH_STYLES.items():
        xml = xml.replace(f'<w:pStyle w:val="{old}" />', f'<w:pStyle w:val="{new}" />')
    for style in KEEP_WITH_NEXT:
        xml = xml.replace(f'<w:pStyle w:val="{style}" />', f'<w:pStyle w:val="{style}" /><w:keepNext />')
    for old, new in TABLE_STYLES.items():
        xml = xml.replace(f'<w:tblStyle w:val="{old}" />', f'<w:tblStyle w:val="{new}" />')
    for style in UNDEFINED_RUN_STYLES:
        xml = xml.replace(f'<w:rStyle w:val="{style}" />', "")
    xml = TABLE.sub(fix_table, xml)
    captions = xml.count('<w:fldSimple w:instr="SEQ ')
    xml, replaced = CAPTION.subn(fix_caption, xml)
    if replaced != captions:
        sys.exit(f"postprocess: {replaced} of {captions} captions matched; pandoc output changed?")
    return xml


def odd_header_file(files: dict[str, bytes]) -> str:
    """Header used for odd pages: the 'default' header reference of the section."""
    document = files["word/document.xml"].decode()
    rel_id = re.search(r'<w:headerReference w:type="default" r:id="([^"]+)"', document)[1]
    rels = files["word/_rels/document.xml.rels"].decode()
    target = re.search(rf'Id="{rel_id}"[^>]*Target="([^"]+)"', rels)[1]
    return f"word/{target}"


def fix_odd_header(xml: str, running_head: str) -> str:
    """Put the running head into the first text run before the tab, empty the others."""
    head, tab, rest = xml.partition("<w:tab/></w:r>")
    texts = iter([running_head])
    head = re.sub(
        r"<w:t( [^>]*)?>[^<]*</w:t>",
        lambda m: f'<w:t xml:space="preserve">{xml_text(next(texts, ""))}</w:t>',
        head,
    )
    return head + tab + rest


def fix_core(xml: str, title: str, author: str) -> str:
    xml = re.sub(r"<dc:title>.*?</dc:title>|<dc:title/>", f"<dc:title>{xml_text(title)}</dc:title>", xml)
    return re.sub(r"<dc:creator>.*?</dc:creator>|<dc:creator/>", f"<dc:creator>{xml_text(author)}</dc:creator>", xml)


def main(docx_path: Path, tex_path: Path) -> None:
    tex = tex_path.read_text(encoding="utf-8")
    running_head = (
        latex_arg(tex, r"\\runningauthors\{(.*?)\}") + ": " + latex_arg(tex, r"\\runningtitle\{(.*?)\}\n")
    )
    title = latex_arg(tex, r"pdftitle\s*=\s*\{(.*?)\}")
    author = latex_arg(tex, r"pdfauthor\s*=\s*\{(.*?)\}")

    with zipfile.ZipFile(docx_path) as z:
        infos = z.infolist()
        files = {info.filename: z.read(info) for info in infos}

    header = odd_header_file(files)
    files["word/document.xml"] = fix_document(files["word/document.xml"].decode()).encode()
    files[header] = fix_odd_header(files[header].decode(), running_head).encode()
    files["docProps/core.xml"] = fix_core(files["docProps/core.xml"].decode(), title, author).encode()

    with zipfile.ZipFile(docx_path, "w", zipfile.ZIP_DEFLATED) as z:
        for info in infos:
            z.writestr(info, files[info.filename])


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
