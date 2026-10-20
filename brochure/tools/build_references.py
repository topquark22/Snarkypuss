#!/usr/bin/env python3
"""Render the public references into a staged gh-pages checkout (requires Pandoc)."""
import argparse
import html
from pathlib import Path
import shutil
import subprocess

from build import read_edition

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = {
    'sources': ('Brochure sources', 'Provenance for the brochure’s dated legislative and industry claims. The source record retains its original access dates.'),
    'legal-analysis': ('Bill C-22 and Snarkypuss users', 'Analysis of the June 18, 2026 bill text, distinguishing personal use from serving other users. Not legal advice or a statement of current law.'),
}


def render(site):
    if not shutil.which('pandoc'):
        raise SystemExit('Pandoc is required: install pandoc before building reference pages.')
    home = site / 'index.html'
    text = home.read_text(encoding='utf-8')
    marker = '  <h2>Install it</h2>'
    if 'id="references"' not in text and marker not in text:
        raise SystemExit('Homepage has no reference section or expected Install it heading; no files changed.')
    snapshot = read_edition()['snapshot_text']
    output = site / 'references'
    output.mkdir(exist_ok=True)
    style = (ROOT / 'templates/references.css').read_text(encoding='utf-8')
    (output / 'references.css').write_text(style, encoding='utf-8')
    nav = '<nav aria-label="Reference navigation"><a href="../">Home</a> · <a href="./">References</a> · <a href="sources.html">Sources</a> · <a href="legal-analysis.html">Bill C-22 analysis</a></nav>'

    def page(title, body):
        return ('<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
                f'<title>{html.escape(title)} — Snarkypuss</title>\n'
                '<link rel="icon" href="../favicon.svg" type="image/svg+xml">\n'
                '<link rel="stylesheet" href="references.css">\n</head>\n'
                f'<body><div class="wrap">{nav}<main>{body}</main>'
                '<footer>Snarkypuss · Reference material for the brochure. Dates and limitations are stated in each document.</footer>'
                '</div></body>\n</html>\n')

    for slug, (title, description) in DOCUMENTS.items():
        source = (ROOT / 'references' / f'{slug}.md').read_text(encoding='utf-8')
        fragment = subprocess.run(
            ['pandoc', '--from=markdown+autolink_bare_uris', '--to=html5', '--wrap=none'],
            input=source, text=True, capture_output=True, check=True).stdout
        for other in DOCUMENTS:
            fragment = fragment.replace(f'href="{other}.md"', f'href="{other}.html"')
        # Tables must remain usable on narrow screens without widening the entire page.
        fragment = fragment.replace('<table>', '<div class="table-scroll" role="region" aria-label="Reference table" tabindex="0"><table>').replace('</table>', '</table></div>')
        body = f'<p class="context">{html.escape(description)}</p><p><a href="{slug}.md" download>Download Markdown</a></p><article>{fragment}</article>'
        (output / f'{slug}.html').write_text(page(title, body), encoding='utf-8')
        (output / f'{slug}.md').write_text(source, encoding='utf-8')
    body = '<h1>Sources and legal analysis</h1><p>Read the evidence behind the brochure and the separate analysis of how Bill C-22 could apply to a Snarkypuss operator.</p><ul>'
    for slug, (title, description) in DOCUMENTS.items():
        body += f'<li><a href="{slug}.html">{html.escape(title)}</a><p>{html.escape(description)}</p></li>'
    body += f'</ul><p>The brochure’s legislative snapshot is {snapshot}. The legal analysis examines the June 18, 2026 bill text; publishing it does not update either document’s legislative cutoff.</p><p><a href="../brochure/">Brochure editions and downloads</a></p>'
    (output / 'index.html').write_text(page('Sources and legal analysis', body), encoding='utf-8')
    if 'id="references"' not in text:
        section = f'''  <section aria-labelledby="references">
    <h2 id="references">Sources and legal analysis</h2>
    <p>Read the <a href="references/sources.html">sources behind the brochure</a>
      and the <a href="references/legal-analysis.html">Bill C-22 analysis for Snarkypuss users</a>,
      including personal use versus offering a gateway to others.</p>
    <p class="small mute">The analysis examines the June 18, 2026 bill text;
      it does not update the brochure’s {snapshot} legislative snapshot.
      Both pages include Markdown downloads.</p>
  </section>

'''
        home.write_text(text.replace(marker, section + marker, 1), encoding='utf-8')
    print(f'Reference pages, Markdown downloads, and homepage links written to {site}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site-root', type=Path, required=True, help='Staged gh-pages root containing index.html; existing media and PDFs are preserved.')
    render(parser.parse_args().site_root.resolve())
