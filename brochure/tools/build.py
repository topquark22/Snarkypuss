#!/usr/bin/env python3
"""Build the Snarkypuss A5 brochure from per-page Markdown sources.

The Markdown under brochure/content/ is the source of truth. Page boundaries
are recorded there as <!-- page: N --> markers. LaTeX is a generated
publishing format, and build/pages/ is a derived artifact.
"""
import argparse
import datetime
import re
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "content"
EDITION = ROOT / "edition.conf"
QR_TEX = ROOT / "images" / "diagrams" / "qr-site.tex"
DERIVED = ROOT / "build" / "pages"
TEMPLATE = ROOT / "templates" / "brochure.tex"
BUILD = ROOT / "build"
def artifacts(press=False):
    """Working filenames for the compile.

    Kept plain and stable: they become the TeX jobname, and a jobname
    containing dots or a date is asking for trouble. The finished PDF is
    renamed to its published name afterwards -- see published_name.
    """
    stem = "snarkypuss-press" if press else "snarkypuss"
    return BUILD / f"{stem}.tex", BUILD / f"{stem}.pdf"


def published_name(edition, press=False):
    """The delivered filename: snarkypuss[-press]_<snapshot>[_<patch>].pdf

    The date is the legislative snapshot, at whatever precision edition.conf
    gives it, so the filename says what the content is current to rather than
    when the file happened to be built. The trailing number is the patch
    component of `version`, present only when version carries a third part:
    1.0 gives no suffix, 1.0.2 gives _2.
    """
    stem = "snarkypuss-press" if press else "snarkypuss"
    parts = [stem, edition["snapshot_raw"]]
    patch = edition.get("patch")
    if patch is not None:
        parts.append(patch)
    return BUILD / ("_".join(parts) + ".pdf")

TRIM_MM = (148.0, 210.0)      # A5
BLEED_MM = 3.0                # artwork overhang the printer trims into
MARK_MM = 5.0                 # zone outside the bleed for trim marks
MARGIN_MM = BLEED_MM + MARK_MM
MM_TO_BP = 72.0 / 25.4

PAGE_COUNT = 16
PAGE_MARKER_RE = __import__("re").compile(
    r"^<!--\s*page:\s*(\d+)((?:\s+[a-z_]+=\S+)*)\s*-->\s*$")
DEFAULT_BODY_SIZE = 11.0


def press_setup():
    """TrimBox, BleedBox and trim marks for the press edition."""
    def bp(mm):
        return round(mm * MM_TO_BP, 4)

    t0, b0 = bp(MARGIN_MM), bp(MARGIN_MM)
    t1, b1 = bp(MARGIN_MM + TRIM_MM[0]), bp(MARGIN_MM + TRIM_MM[1])
    d0, e0 = bp(MARK_MM), bp(MARK_MM)
    d1, e1 = bp(MARK_MM + TRIM_MM[0] + 2 * BLEED_MM), bp(MARK_MM + TRIM_MM[1] + 2 * BLEED_MM)

    marks = []
    for xs, ys in ((0, 0), (1, 0), (0, 1), (1, 1)):
        x = f"{MARGIN_MM}mm" if not xs else f"\\paperwidth-{MARGIN_MM}mm"
        y = f"{MARGIN_MM}mm" if not ys else f"\\paperheight-{MARGIN_MM}mm"
        hx = "0mm" if not xs else "\\paperwidth"
        hx2 = f"{MARK_MM - 1}mm" if not xs else f"\\paperwidth-{MARK_MM - 1}mm"
        vy = "0mm" if not ys else "\\paperheight"
        vy2 = f"{MARK_MM - 1}mm" if not ys else f"\\paperheight-{MARK_MM - 1}mm"
        marks.append(
            f"    \\draw[black,line width=0.25pt] "
            f"($(current page.south west)+({hx},{y})$) -- "
            f"($(current page.south west)+({hx2},{y})$);")
        marks.append(
            f"    \\draw[black,line width=0.25pt] "
            f"($(current page.south west)+({x},{vy})$) -- "
            f"($(current page.south west)+({x},{vy2})$);")

    return (
        "\\pdfvariable pageattr{/TrimBox ["
        f"{t0} {b0} {t1} {b1}"
        "] /BleedBox ["
        f"{d0} {e0} {d1} {e1}"
        "]}\n"
        "\\renewcommand{\\cropmarks}{%\n"
        "  \\begin{tikzpicture}[remember picture,overlay]\n"
        + "\n".join(marks) + "\n"
        "  \\end{tikzpicture}%\n"
        "}"
    )
A5_PT = (419.528, 595.276)
PRESS_PT = tuple(round((d + 2 * MARGIN_MM) * MM_TO_BP, 3) for d in TRIM_MM)

LAYOUTS = {"cover", "standard", "spread-left", "spread-right", "backcover"}

LATEX_ESCAPES = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
    "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}

FIGURE_RE = re.compile(
    r"<!--\s*figure:\s*([a-z0-9-]+)\s+width=([0-9]+)%\s+height=([0-9.]+)mm\s*-->")
DIAGRAM_RE = re.compile(
    r"<!--\s*diagram:\s*([a-z0-9-]+)(?:\s+height=([0-9.]+)mm)?\s*-->")
KEYLINE_RE = re.compile(r"<!--\s*keyline:\s*(.+?)\s*-->")
NOTE_RE = re.compile(r"<!--\s*note:\s*(.+?)\s*-->")
SNAPSHOT_RE = re.compile(r"<!--\s*snapshot\s*-->")
EDITION_RE = re.compile(r"<!--\s*edition\s*-->")


class BuildError(Exception):
    pass


# ---------------------------------------------------------------------------
# Edition metadata
# ---------------------------------------------------------------------------

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")


def check_qr(site_url):
    """The committed QR must encode the address the brochure prints.

    qr-site.tex records its URL in a header comment. If the two disagree,
    somebody changed the address without reissuing the code, and the printed
    brochure would send readers somewhere else.
    """
    if not QR_TEX.exists():
        raise BuildError(
            f"missing {QR_TEX.name}; run: python3 tools/make_qr.py")
    head = QR_TEX.read_text(encoding="utf-8").splitlines()[0]
    m = re.search(r"QR code for (\S+)", head)
    if not m:
        raise BuildError(f"{QR_TEX.name}: no URL header; regenerate with tools/make_qr.py")
    encoded = m.group(1).rstrip("/")
    if encoded != site_url:
        raise BuildError(
            f"QR mismatch: {QR_TEX.name} encodes {encoded}, but edition.conf "
            f"says {site_url}.\n            Reissue it: python3 tools/make_qr.py")


def read_edition():
    """Version, legislative snapshot, and build date.

    The build date is the current date, or SOURCE_DATE_EPOCH when set, so a
    release can be reproduced byte for byte. The legislative snapshot is never
    derived from either -- rebuilding is not the same as re-verifying.
    """
    if not EDITION.exists():
        raise BuildError(f"missing {EDITION.name}")
    conf = {}
    for lineno, line in enumerate(EDITION.read_text(encoding="utf-8").splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if "=" not in line:
            raise BuildError(f"edition.conf:{lineno}: expected key = value")
        key, _, value = line.partition("=")
        conf[key.strip()] = value.strip()

    for key in ("version", "legislative_snapshot", "site_url"):
        if key not in conf:
            raise BuildError(f"edition.conf: missing {key}")

    # YYYY-MM-DD when the day is meaningful, YYYY-MM when only the month is.
    raw = conf["legislative_snapshot"]
    parts = raw.split("-")
    try:
        if len(parts) == 3:
            snapshot = datetime.date(*(int(x) for x in parts))
            day_known = True
        elif len(parts) == 2:
            snapshot = datetime.date(int(parts[0]), int(parts[1]), 1)
            day_known = False
        else:
            raise ValueError(raw)
    except (ValueError, TypeError):
        raise BuildError(
            "edition.conf: legislative_snapshot must be YYYY-MM-DD or YYYY-MM, "
            f"got {raw!r}")

    stamp = os.environ.get("SOURCE_DATE_EPOCH")
    if stamp:
        built = datetime.datetime.utcfromtimestamp(int(stamp)).date()
    else:
        built = datetime.date.today()

    months_old = (built.year - snapshot.year) * 12 + (built.month - snapshot.month)
    if day_known and built.day < snapshot.day:
        months_old -= 1
    site_url = conf["site_url"].rstrip("/")
    version_parts = conf["version"].split(".")
    return {
        "version": conf["version"],
        "patch": version_parts[2] if len(version_parts) >= 3 else None,
        "snapshot_raw": raw,
        "site_url": site_url,
        "site_display": re.sub(r"^https?://", "", site_url),
        "snapshot_text": (
            f"{snapshot.day} {MONTHS[snapshot.month - 1]} {snapshot.year}"
            if day_known else f"{MONTHS[snapshot.month - 1]} {snapshot.year}"),
        "built_text": f"{built.day} {MONTHS[built.month - 1]} {built.year}",
        "months_old": months_old,
        "warn_after": int(conf.get("snapshot_warn_months", 6)),
    }


# ---------------------------------------------------------------------------
# Markdown vocabulary
# ---------------------------------------------------------------------------

def escape(text):
    return "".join(LATEX_ESCAPES.get(ch, ch) for ch in text)


def inline(text):
    parts = re.split(r"(`[^`]+`|\*\*[^*]+\*\*)", text)
    out = []
    for part in parts:
        if part.startswith("`") and part.endswith("`"):
            out.append(r"\texttt{" + escape(part[1:-1]) + "}")
        elif part.startswith("**") and part.endswith("**"):
            out.append(r"\textbf{" + escape(part[2:-2]) + "}")
        else:
            out.append(escape(part))
    return "".join(out)


SITE_TOKEN = "{{site}}"


def markdown_to_latex(text, site_display=""):
    text = text.replace(SITE_TOKEN, site_display)
    out, para, bullets = [], [], []

    def flush_para():
        if para:
            out.append(inline(" ".join(para)))
            para.clear()

    def flush_bullets():
        if bullets:
            items = "\n".join(r"  \item " + inline(b) for b in bullets)
            out.append("\\begin{itemize}\n" + items + "\n\\end{itemize}")
            bullets.clear()

    def flush():
        flush_para()
        flush_bullets()

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue

        if SNAPSHOT_RE.fullmatch(line):
            flush()
            out.append(r"\snapshotline")
            continue
        if EDITION_RE.fullmatch(line):
            flush()
            out.append(r"\editionline")
            continue

        for pattern, command in ((FIGURE_RE, None), (DIAGRAM_RE, r"\diagraminput"),
                                 (KEYLINE_RE, r"\keyline"), (NOTE_RE, r"\smallnote")):
            m = pattern.fullmatch(line)
            if not m:
                continue
            flush()
            if pattern is FIGURE_RE:
                name, width, height = m.groups()
                out.append(r"\brochurefigure{%s}{%s}{%s}"
                           % (escape(name), float(width) / 100.0, height))
            elif pattern is DIAGRAM_RE:
                name, height = m.group(1), m.group(2)
                opt = "[%s]" % height if height else ""
                out.append(r"\diagraminput%s{%s}" % (opt, escape(name)))
            else:
                out.append("%s{%s}" % (command, inline(m.group(1))))
            break
        else:
            if line.startswith("- "):
                flush_para()
                bullets.append(line[2:])
            elif line.startswith("# "):
                flush()
                out.append(r"\chapterheading{" + inline(line[2:]) + "}")
            elif line.startswith("## "):
                flush()
                out.append(r"\sectionheading{" + inline(line[3:]) + "}")
            else:
                flush_bullets()
                para.append(line)

    flush()
    return "\n\n".join(out)


# ---------------------------------------------------------------------------
# Page sources
# ---------------------------------------------------------------------------

def split_pages(path):
    """Split one content file into pages at <!-- page: N ... --> markers."""
    found, current, body = [], None, []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        m = PAGE_MARKER_RE.match(line.strip())
        if not m:
            if current is None:
                if line.strip():
                    raise BuildError(
                        f"{path.name}:{lineno}: content before the first page marker")
                continue
            body.append(line)
            continue
        if current is not None:
            found.append((current, "\n".join(body).strip()))
        number, attrtext = m.groups()
        attrs = {}
        for pair in attrtext.split():
            key, _, value = pair.partition("=")
            attrs[key] = value
        attrs["page"] = int(number)
        attrs.setdefault("layout", "standard")
        attrs["source"] = f"{path.name}:{lineno}"
        if attrs["layout"] not in LAYOUTS:
            raise BuildError(f"{attrs['source']}: unknown layout {attrs['layout']!r}")
        current, body = attrs, []
    if current is not None:
        found.append((current, "\n".join(body).strip()))
    return found


def load_pages():
    """Pages are derived from content/, which is the source of truth."""
    files = sorted(CONTENT.glob("*.md"))
    if not files:
        raise BuildError(f"no content files found in {CONTENT}")

    pages = []
    for path in files:
        pages.extend(split_pages(path))
    if not pages:
        raise BuildError("no page markers found; content files need <!-- page: N --> markers")
    pages.sort(key=lambda item: item[0]["page"])

    numbers = [meta["page"] for meta, _ in pages]
    if numbers != list(range(1, PAGE_COUNT + 1)):
        raise BuildError(
            f"page sequence must be 1..{PAGE_COUNT} with no gaps or duplicates; got {numbers}")

    # A saddle-stitched booklet puts an even page on the left of each facing
    # pair. A spread that starts on an odd page does not face its partner.
    index = {meta["page"]: meta for meta, _ in pages}
    for meta, _ in pages:
        n, layout = meta["page"], meta["layout"]
        if layout == "spread-left":
            if n % 2:
                raise BuildError(
                    f"{meta['source']}: page {n} is spread-left, but {n} is a "
                    f"right-hand page; a spread must start on an even page")
            partner = index.get(n + 1)
            if not partner or partner["layout"] != "spread-right":
                raise BuildError(
                    f"{meta['source']}: page {n} is spread-left but page {n+1} "
                    f"is not spread-right")
        if layout == "spread-right":
            partner = index.get(n - 1)
            if not partner or partner["layout"] != "spread-left":
                raise BuildError(
                    f"{meta['source']}: page {n} is spread-right but page {n-1} "
                    f"is not spread-left")
    return pages


def write_derived(pages):
    """Write the split pages for inspection. Generated, not source."""
    DERIVED.mkdir(parents=True, exist_ok=True)
    for meta, body in pages:
        lines = [f"<!-- derived from {meta['source']} - do not edit -->",
                 f"<!-- page: {meta['page']} layout={meta['layout']} -->", ""]
        (DERIVED / f"{meta['page']:02d}.md").write_text(
            "\n".join(lines) + body + "\n", encoding="utf-8")


def generate_tex(verbose=False, body_size=DEFAULT_BODY_SIZE, press=False):
    edition = read_edition()
    pages = load_pages()
    write_derived(pages)
    chunks = []
    for meta, body in pages:
        n, layout = meta["page"], meta["layout"]
        if layout in ("cover", "backcover"):
            art = meta.get("art")
            if not art:
                raise BuildError(f"page {n}: {layout} layout requires an 'art' path")
            if not (ROOT / art).exists():
                raise BuildError(f"{meta['source']}: cover art not found: {art}")
            command = r"\backcoverpage" if layout == "backcover" else r"\coverpage"
            chunks.append("%s{%s}" % (command, art))
            continue
        chunks.append("\\begin{snarkypage}{%d}{%s}\n%s\n\\end{snarkypage}"
                      % (n, layout, markdown_to_latex(body, edition["site_display"])))

    template = TEMPLATE.read_text(encoding="utf-8")
    if "%%CONTENT%%" not in template:
        raise BuildError("template is missing %%CONTENT%% placeholder")
    BUILD.mkdir(parents=True, exist_ok=True)
    if "%%BODYSIZE%%" not in template:
        raise BuildError("template is missing %%BODYSIZE%% placeholder")
    pad = MARGIN_MM if press else 0.0
    subs = {
        "%%BODYSIZE%%": f"{body_size}pt",
        "%%PAPERW%%": f"{TRIM_MM[0] + 2 * pad}mm",
        "%%PAPERH%%": f"{TRIM_MM[1] + 2 * pad}mm",
        "%%TOP%%": f"{15 + pad}mm",
        "%%BOTTOM%%": f"{16 + pad}mm",
        "%%INNER%%": f"{16 + pad}mm",
        "%%OUTER%%": f"{14 + pad}mm",
        "%%PRESSSETUP%%": press_setup() if press else "",
        "%%TRIMOFFSET%%": f"{pad}mm",
        "%%SITEURL%%": edition["site_display"],
        "%%VERSION%%": edition["version"],
        "%%SNAPSHOT%%": edition["snapshot_text"],
        "%%BUILT%%": edition["built_text"],
    }
    tex = template
    for key, value in subs.items():
        if key not in tex:
            raise BuildError(f"template is missing {key} placeholder")
        tex = tex.replace(key, value)
    tex = tex.replace("%%CONTENT%%", "\n".join(chunks))
    tex_path, _ = artifacts(press)
    BUILD.mkdir(parents=True, exist_ok=True)
    tex_path.write_text(tex, encoding="utf-8")
    if verbose:
        print(f"generated {tex_path}")
    return pages


FONT_FILES = ("LibertinusSerif-Regular.otf", "LibertinusSans-Regular.otf")


def check_fonts():
    """Fail with a useful message rather than a wall of fontspec output.

    kpsewhich is part of every TeX distribution. If it cannot find the
    Libertinus faces, the font package is missing -- which produces an error
    that does not name the package you actually need.
    """
    kpsewhich = shutil.which("kpsewhich")
    if not kpsewhich:
        return
    missing = [f for f in FONT_FILES
               if not subprocess.run([kpsewhich, f], text=True,
                                     capture_output=True).stdout.strip()]
    if missing:
        raise BuildError(
            "the Libertinus fonts are not installed: " + ", ".join(missing) +
            "\n            Debian/Ubuntu: sudo apt install texlive-fonts-extra"
            "\n            MiKTeX:        miktex packages install libertinus-fonts"
            "\n            TeX Live:      tlmgr install libertinus-fonts")


def compile_pdf(verbose=False, press=False):
    engine = shutil.which("lualatex")
    if not engine:
        raise BuildError("lualatex was not found in PATH")
    check_fonts()
    # TeX treats a backslash as an escape, so hand it forward-slash paths even
    # on Windows. Both MiKTeX and TeX Live accept them.
    command = [engine, "-interaction=nonstopmode", "-halt-on-error",
               "-output-directory", BUILD.as_posix(),
               artifacts(press)[0].as_posix()]
    log = ""
    for _ in range(2):
        env = dict(os.environ, max_print_line="10000", error_line="254", half_error_line="238")
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, env=env)
        log = result.stdout
        if verbose:
            print(log[-4000:])
        if result.returncode:
            print(log[-4000:], file=sys.stderr)
            raise BuildError("LuaLaTeX compilation failed")
    return log


# ---------------------------------------------------------------------------
# Validation and fit reporting
# ---------------------------------------------------------------------------

def fit_report(log):
    rows = []
    for m in re.finditer(
            r"PAGEFIT page=(\d+) layout=(\S+)\s+natural=([\d.]+)pt depth=([\d.]+)pt\s+avail=([\d.]+)pt",
            log):
        page, layout, nat, dep, avail = m.groups()
        used = float(nat) + float(dep)
        avail = float(avail)
        rows.append((int(page), layout, used, avail, used / avail * 100.0))
    rows.sort()
    return rows


def print_fit(rows):
    if not rows:
        return
    print("\n  page  layout         fill    status")
    print("  ----  -------------  ------  --------------------")
    for page, layout, used, avail, pct in rows:
        if pct > 100.0:
            status = f"OVERFLOW by {used - avail:.0f}pt (~{(used-avail)/14:.0f} lines)"
        elif pct < 55.0:
            status = "very light"
        elif pct < 75.0:
            status = "light"
        else:
            status = "ok"
        print(f"  {page:>4}  {layout:<13}  {pct:>5.1f}%  {status}")


def validate_pdf(press=False, log=""):
    """Check the produced PDF.

    pdfinfo (poppler) gives the strongest check, reading page count and page
    size out of the finished file. It is standard on Linux and macOS but is
    not part of a Windows TeX installation, so when it is absent we fall back
    to the engine's own report of what it wrote. That still catches a wrong
    page count; it cannot independently confirm the page size.
    """
    pdf = artifacts(press)[1]
    if not pdf.exists():
        raise BuildError("PDF was not produced")

    pdfinfo = shutil.which("pdfinfo")
    if not pdfinfo:
        m = re.search(r"Output written on \S+ \((\d+) pages?", log)
        if not m:
            raise BuildError(
                "cannot verify the PDF: pdfinfo is not in PATH and the LaTeX "
                "log did not report a page count")
        count = int(m.group(1))
        if count != PAGE_COUNT:
            raise BuildError(f"expected exactly {PAGE_COUNT} pages, got {count}")
        print("note: pdfinfo not found; page size not independently verified")
        return count

    info = subprocess.run([pdfinfo, str(pdf)], text=True,
                          capture_output=True, check=True).stdout
    pages = re.search(r"^Pages:\s+(\d+)$", info, re.M)
    if not pages:
        raise BuildError("could not determine PDF page count")
    count = int(pages.group(1))
    if count != PAGE_COUNT:
        raise BuildError(f"expected exactly {PAGE_COUNT} pages, got {count}")
    size = re.search(r"^Page size:\s+([0-9.]+) x ([0-9.]+) pts", info, re.M)
    if not size:
        raise BuildError("could not determine PDF page size")
    expected = PRESS_PT if press else A5_PT
    w, h = map(float, size.groups())
    if abs(w - expected[0]) > 1 or abs(h - expected[1]) > 1:
        label = "press (trim + bleed + marks)" if press else "A5 trim"
        raise BuildError(f"expected {label} page size {expected}, got {w} x {h} pt")
    return count


def clean():
    if BUILD.exists():
        for path in BUILD.iterdir():
            if path.is_file():
                path.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tex-only", action="store_true")
    parser.add_argument("--fit", action="store_true",
                        help="report per-page fill and exit non-zero on overflow")
    parser.add_argument("--body-size", type=float, default=DEFAULT_BODY_SIZE,
                        help="body text size in points; the whole type scale derives from it")
    parser.add_argument("--press", action="store_true",
                        help="press edition: adds 3mm bleed, trim marks, TrimBox/BleedBox")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    if args.clean:
        clean()
        return

    edition = read_edition()
    check_qr(edition["site_url"])
    generate_tex(args.verbose, args.body_size, args.press)
    if args.tex_only:
        return

    log = compile_pdf(args.verbose, args.press)
    count = validate_pdf(args.press, log)
    target = published_name(edition, args.press)
    artifacts(args.press)[1].replace(target)
    rows = fit_report(log)
    geometry = "press, trim + 3mm bleed + marks" if args.press else "screen, A5 trim"
    print(f"built {target} ({count} pages, {geometry}) at {args.body_size}pt body")
    print_fit(rows)

    print(f"\nedition {edition['version']}, built {edition['built_text']}; "
          f"legislative snapshot {edition['snapshot_text']} "
          f"({edition['months_old']} months old)")
    if edition["months_old"] >= edition["warn_after"]:
        print(f"WARNING: the legislative snapshot is {edition['months_old']} months old.\n"
              f"         Re-check pages 2-4 against references/sources.md, then update\n"
              f"         legislative_snapshot in edition.conf. Rebuilding does not\n"
              f"         refresh the facts.", file=sys.stderr)

    overflow = [r for r in rows if r[4] > 100.0]
    if overflow:
        print(f"\n{len(overflow)} page(s) overflow the text block.")
        if args.fit:
            sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except BuildError as exc:
        print(f"build failed: {exc}", file=sys.stderr)
        sys.exit(1)
