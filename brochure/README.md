# Snarkypuss brochure

A5 portrait, 16 pages, full colour, designed for saddle-stitch booklet
printing on four folded A4 sheets.

`PLAN.md` is the editorial plan — audience, tone, the non-partisan standard,
project positioning, and what belongs on each page. This file is everything
needed to rebuild the PDF from a clean machine.

## Build

```bash
cd brochure
python3 tools/build.py
```

Output is the screen edition: 148 × 210 mm, the A5 trim size, for reading and
for distributing as a download. It is named for its content rather than its
build:

```
snarkypuss[-press]_<legislative_snapshot>[_<patch>].pdf
```

The date comes from `legislative_snapshot`, at whatever precision
`edition.conf` gives it, so a downloaded copy states on its face what it is
current to. The trailing number is the third component of `version`, present
only if there is one — `1.0` yields no suffix, `1.0.2` yields `_2`. Examples:

| edition.conf | screen | press |
|---|---|---|
| `1.0` / `2026-09-17` | `snarkypuss_2026-09-17.pdf` | `snarkypuss-press_2026-09-17.pdf` |
| `1.0.2` / `2026-09-17` | `snarkypuss_2026-09-17_2.pdf` | `snarkypuss-press_2026-09-17_2.pdf` |
| `1.0` / `2026-09` | `snarkypuss_2026-09.pdf` | `snarkypuss-press_2026-09.pdf` |

The compile itself still runs under the plain stem `snarkypuss`, because that
becomes the TeX jobname and a jobname full of dots and dates causes more
trouble than it is worth. The finished PDF is renamed afterwards. The build fails
rather than warns if the result is not exactly 16 pages at the expected size.

For the printer:

```bash
python3 tools/build.py --press
```

Output follows the same naming, with `-press` after the stem.

### The two editions

Both come from the same sources and the same artwork. Only the page geometry
differs.

| | Screen | Press |
|---|---|---|
| Page (MediaBox) | 148 × 210 mm | 164 × 226 mm |
| TrimBox | — | 148 × 210 mm, inset 8 mm |
| BleedBox | — | 154 × 216 mm, inset 5 mm |
| Trim marks | no | yes, in the 5 mm zone outside the bleed |
| Cover artwork | overhang clipped at the page edge | overhang visible, 3 mm on each edge |

The text block sits identically relative to the trim in both, because the
press edition shifts the margins outward by the same 8 mm it adds to the
paper. The fill report is therefore the same for both, and a page that fits
one fits the other.

There is only one set of cover images. The press artwork already contains the
trim composition in its centre, so the screen edition centres the same file
on a smaller page and lets the 3 mm overhang fall outside the page box. Do
not keep a separate trim-sized copy of the covers — two versions of the same
image will drift, and the only thing that distinguishes them is discarded at
the guillotine anyway.

### Options

| Flag | Effect |
|---|---|
| `--press` | Press edition: adds 3 mm bleed, trim marks, and PDF TrimBox/BleedBox. Writes `build/snarkypuss-press.pdf`. |
| `--body-size PT` | Body text size. The entire type scale derives from it. Default 11.0. |
| `--fit` | Exit non-zero if any page overflows its text block. Use in CI. |
| `--tex-only` | Write `build/snarkypuss.tex` without running LuaLaTeX. |
| `--verbose` | Show LaTeX output. |
| `--clean` | Remove build artifacts. |

Every build prints a per-page fill report. A page over 100% overprints its
box; it does not repaginate, because each page is a fixed-height box. That is
deliberate — the page count cannot drift, so overflow is a build diagnostic
rather than something you discover by flipping through the PDF.

## Toolchain

Debian/Ubuntu:

```bash
sudo apt install \
  texlive-luatex texlive-latex-base texlive-latex-recommended \
  texlive-latex-extra texlive-pictures texlive-fonts-extra \
  poppler-utils python3
```

| Requirement | Provided by | Used for |
|---|---|---|
| `lualatex` | texlive-luatex | typesetting engine |
| `pdfinfo` | poppler-utils | page count and page size validation |
| Python 3 (no third-party packages) | python3 | `tools/build.py` |
| geometry | texlive-latex-base | A5 page geometry |
| fontspec, graphicx, xcolor, ragged2e | texlive-latex-recommended | fonts, images, colour, ragged setting |
| adjustbox, enumitem, hyperref | texlive-latex-extra | diagram fitting, lists, links |
| tikz / pgf | texlive-pictures | all four diagrams |
| Libertinus Serif, Libertinus Sans | texlive-fonts-extra | body and display faces |

### Windows

Install a Windows TeX distribution and run the build from `cmd` or
PowerShell with native Windows Python. MiKTeX is the easier of the two,
because it fetches missing packages on demand rather than needing the right
collections chosen up front:

```
winget install MiKTeX.MiKTeX
winget install Python.Python.3.12
python tools\build.py
```

TeX Live for Windows works equally well if you already have it.

MiKTeX does not ship the Libertinus fonts by default. Either let it fetch
them on demand, or install them up front:

```
miktex packages install libertinus-fonts
```

`pdfinfo` is a poppler tool and is not part of either distribution. The build
does not require it: without it, the page count is taken from the engine's own
report instead, and it says so. Page size then goes unverified, which only
matters if you are editing the geometry. To get the stronger check, install
poppler for Windows and put its `bin` on PATH.

Do not run the build under Cygwin against a native Windows TeX. Cygwin gives
POSIX paths that a Windows binary cannot resolve, and the failure is obscure.
Use Cygwin's own TeX Live, WSL2, or native Windows throughout -- not a mixture.

The Libertinus faces are loaded by **filename** through fontspec and resolved
by kpathsea from the TeX tree, so they do not need to be installed as system
fonts. Do not change the template to load them by family name -- that goes
through the operating system's font database and breaks on any machine where
the fonts live only in the TeX tree, which is most of them.

If the fonts are missing the build says so before invoking LaTeX, and names
the package to install for your distribution.

## Source files

Everything below is authored input and belongs in version control.

```
content/          the prose, four thematic files with page markers
templates/        brochure.tex — the whole design system
tools/            build.py — the only entry point
images/           cover art and diagrams
references/       sources.md — provenance for the dated claims
edition.conf      version, legislative snapshot, staleness threshold
PLAN.md           editorial plan
README.md         this file
```

`build/` is generated and is ignored by `.gitignore`. That includes
`build/pages/`, the per-page split the build writes for inspection. Those
files are derived — never edit them, and never commit them.

### Page markers

`content/` holds the prose and is the single source of truth. Pagination is
recorded inline with page markers, because where a page begins is an
editorial decision, not a typesetting side effect:

```markdown
<!-- page: 6 layout=spread-left -->
```

Everything after a marker belongs to that page, until the next marker.
`layout` is one of `cover`, `standard`, `spread-left`, `spread-right`,
`backcover`, and defaults to `standard`. Cover layouts also take `art=`, a
repository-relative path:

```markdown
<!-- page: 1 layout=cover art=images/cover-bleed.png -->
```

Content files are read in filename order and each owns a contiguous range of
pages. Currently: `01-why.md` covers 1–4, `02-what.md` 5–9,
`03-engineering.md` 10–14, `04-project.md` 15–16.

To move a paragraph from one page to the next, move the page marker — not the
paragraph. To repaginate a whole section, move several markers. The build
validates that pages run 1–16 with no gaps, and that a
`spread-left` falls on an even page with `spread-right` on the page after it.
In a saddle-stitched booklet page 1 is a right-hand page, so facing pairs are
2–3, 4–5, 6–7, 8–9, 10–11, 12–13 and 14–15. A spread beginning on an odd page
would be split by a page turn, so the build refuses it.

### Markdown vocabulary

Deliberately small. Anything the template cannot express through these is a
template change, not a page-source change.

| Syntax | Result |
|---|---|
| `# Heading` | Page-opening heading with accent rule. One per page at most. |
| `## Heading` | Section heading. May begin mid-page by design. |
| `**bold**`, `` `code` `` | Inline emphasis and monospace |
| `- item` | Bulleted list |
| `<!-- note: text -->` | Small grey line, used for dating lines |
| `<!-- keyline: text -->` | Tinted emphasis panel |
| `<!-- diagram: name height=108mm -->` | TikZ fragment from `images/diagrams/name.tex`, scaled to fit within the text width and the given height. Height defaults to 95 mm. |
| `<!-- figure: name width=100% height=45mm -->` | Raster or PDF figure from `images/diagrams/name.pdf` |
| `<!-- snapshot -->` | The legislative dating line, from `edition.conf` |
| `<!-- edition -->` | The publication line: edition, build date, snapshot |
| `{{site}}` | Inline: the site address from `edition.conf` |

Content files must not contain raw LaTeX or manual spacing adjustments. The
template owns typography, colour, geometry and spacing. Page markers are the
one exception, and they carry structure rather than formatting.

## Artwork

Covers are supplied at **1819 × 2551 px**, which is 154 × 216 mm at 300 dpi:
A5 trim plus 3 mm bleed on every edge. The template centres them on the
148 × 210 mm page so the artwork overhangs by 3 mm, and the printer trims into
the overhang.

`images/cover-bleed.png` and `images/back-cover-bleed.png` are the only cover
masters, used by both editions. If cover art is regenerated, match those
dimensions exactly or the bleed will be wrong.

Keep the type at least 5 mm inside the trim. The current front cover title
clears it by roughly a millimetre, which is legal but tighter than ideal for
a saddle-stitched job.

The **front** cover still has its lettering baked into the raster, so changing
its wording means regenerating the artwork.

The **back** cover does not. `images/back-cover-plate.png` is the photographic
plate with all lettering painted out, and the template sets the headline,
wordmark, taglines, address, rule work and disclaimer as live type over it.
The address can therefore be changed without touching artwork. The plate was
derived from `images/back-cover-bleed.png`, which is kept only as the source
for regenerating it.

The QR is vector, not an image. `images/diagrams/qr-site.tex` is generated:

```bash
python3 tools/make_qr.py https://snarkypuss.ca
```

Error-correction level H, so it still scans through a scuff or a fold. Verify
any regenerated code actually decodes before printing — the QR in the
original artwork was an image model's imitation of one and resolved to
nothing.

Diagrams are TikZ fragments, not standalone documents. They use the colour
names defined in `templates/brochure.tex` (`snarkycyan`, `snarkysteel`,
`snarkydeep`, `snarkypale`, `snarkymute`, `snarkyink`), so they cannot be
compiled on their own without that preamble.

## Changing the content

1. Edit the relevant file in `content/`.
2. Rebuild and read the fill report.
3. If a page overflows, move a paragraph to an adjacent page or cut it. Do
   not shrink the type to fit one page — the size is global.
4. If pages 2–4 change, update `references/sources.md` in the same commit.

The type size is the largest that fits the current copy. Raising it means
finding new headroom first; the report tells you which page binds.

## Edition and dating

`edition.conf` carries three things:

```
version = 1.0
legislative_snapshot = 2026-09-17
snapshot_warn_months = 6
```

`version` is the brochure edition. Bump it when you publish a revision.

`site_url` is the project's public address, and the only place it is written.
It reaches the back cover through the template, page 15 through the `{{site}}`
token in `content/`, and the QR through `tools/make_qr.py`. Change it in one
place and reissue the code:

```bash
python3 tools/make_qr.py          # regenerates images/diagrams/qr-site.tex
```

If you forget, the build stops rather than producing a brochure whose printed
address and QR disagree:

```
build failed: QR mismatch: qr-site.tex encodes https://snarkypuss.ca, but
edition.conf says https://snarkypuss.org.
            Reissue it: python3 tools/make_qr.py
```

`qr-site.tex` is committed, not ignored. The build does not run `make_qr.py`
-- deliberately, so that a clone builds with nothing beyond the Python
standard library -- which makes the generated file a build *input*, like the
diagrams.

`legislative_snapshot` is the date against which pages 2–4 were researched and
verified. Give it as `YYYY-MM-DD`, or as `YYYY-MM` when only the month is
meaningful; the brochure prints whichever precision you supply. **Set it by hand, and only after re-checking the claims against
`references/sources.md`.** It is deliberately not derived from the build
date, because rebuilding a PDF is not the same as re-reading the law. If the
two were linked, a rebuild in 2028 would silently claim the legislation
section was current.

### What each version component means

`version` is `MAJOR.MINOR[.PATCH]`:

| Component | Bump it when |
|---|---|
| **MAJOR** | The law changed. Pages 2–4 are re-researched and `legislative_snapshot` moves with it. |
| **MINOR** | The wording of the content changed — corrections, rewrites, anything editorial that leaves the legal position as it was. |
| **PATCH** | Anything else that reaches the printed page: build system, template, typography, artwork, diagrams. |

PATCH is optional. `version = 1.0` is valid and is the normal state of a fresh
MAJOR or MINOR release — there is no need to write `1.0.0`. Add the third
component only once there is a patch revision to record, and the filename
picks it up from that point on:

```
version = 1.0      ->  snarkypuss_2026-09-17.pdf
version = 1.0.1    ->  snarkypuss_2026-09-17_1.pdf
```

MAJOR and MINOR are not optional.

The distinction between MAJOR and the rest is the one that matters most,
because only MAJOR implies the facts were re-verified. `legislative_snapshot`
and MAJOR move together; if you find yourself moving one without the other,
something is wrong.

### A filename caveat

The published filename carries the snapshot date and the PATCH component, not
MAJOR or MINOR. The date is what a reader of a dated document needs, so this
is right for the common case — but it does mean a MINOR bump alone is
invisible in the filename.

`1.0` and `1.1` against the same snapshot both produce
`snarkypuss_2026-09-17.pdf`, and the second overwrites the first. Resetting
PATCH does not help: `1.0.0` and `1.1.0` both yield `_0`.

If that matters — two editions in circulation that cannot be told apart by
filename — there are two ways out: put the full version in the filename
instead of just PATCH, or let PATCH keep counting across MINOR bumps
(`1.0.3` then `1.1.4`) so it never repeats. Neither is implemented; the
current behaviour is to overwrite.

The build does not enforce any of this, and will write over an existing file
of the same name without comment.

The build date is today's date, or `SOURCE_DATE_EPOCH` when set, so a
published edition can be reproduced exactly:

```bash
SOURCE_DATE_EPOCH=$(git log -1 --format=%ct) python3 tools/build.py --press
```

Every build reports both dates and the gap between them. Once the snapshot is
older than `snapshot_warn_months`, the build warns on stderr. It does not
fail — a stale brochure still has to be printable — but the warning is there
so a stale one is never published by accident.

Both dates reach the page through directives rather than typed literals:
`<!-- snapshot -->` on page 2 and `<!-- edition -->` on page 15. Never type
either date into `content/`.

## Time-sensitive content

Pages 2–4 describe Canadian legislation as of a stated date. `sources.md`
records what each claim rests on and lists, in order, what to re-check when
the snapshot is superseded. The dating line on page 2 and the edition line on
page 15 are separate and both need updating.

## Design decisions worth keeping

**Why LuaLaTeX.** The brochure is a modern, full-colour designed document.
LuaLaTeX gives native Unicode, straightforward OpenType font selection, and
strong graphics support, while remaining compatible with the ordinary LaTeX
package ecosystem. `pdflatex` would mean fighting the font handling.

**Why Markdown is the authoring format.** LaTeX is a generated publishing
format, not the primary source. Keeping the prose in Markdown makes it easy
to write, review and diff, and — more importantly — reusable. A PowerPoint
presentation built from the same material is a different presentation format,
not an automatic conversion of the PDF. It will use far less text and may
reorganize the narrative into slide-sized ideas, but it can reuse the
researched facts and their provenance, the section headings and narrative
structure, the character artwork, the architecture and state diagrams, and
the terminology. That reuse is the main reason the content stays independent
of the generated LaTeX.

**Graphics.** Simple geometric and technical diagrams are TikZ, which keeps
them versioned as text, diffable, and consistent with the document's fonts
and palette. Illustrative material involving the Snarkypuss character should
be prepared as external image assets rather than forced into TikZ. Raster
graphics need sufficient resolution for their printed size; vector is
preferred for diagrams and line art.

**Provenance.** The brochure itself is not an academic paper and carries no
footnotes, but the repository must preserve enough provenance to verify every
factual claim and to update time-sensitive material later. Political and
legislative material is presented neutrally: government descriptions of
legislative purpose are identified as such, and privacy concerns, industry
positions and contested interpretations are attributed to their sources
rather than presented as undisputed conclusions.

**Releases.** The finished PDF is not committed. A release process may attach
it to a GitHub release instead.
