#!/usr/bin/env python3
"""Render the public references into a staged gh-pages checkout (requires Pandoc)."""
import argparse
import html
import re
from pathlib import Path
import shutil
import subprocess

from build import read_edition

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = {
    'sources': ('Brochure sources', 'Provenance for the brochure’s dated legislative and industry claims. The source record retains its original access dates.'),
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
    nav = '<nav aria-label="Reference navigation"><a href="../">Home</a> · <a href="./">References</a> · <a href="sources.html">Sources</a></nav>'

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
    body = '<h1>Brochure sources</h1><p>Read the source record behind the brochure’s legislative and industry claims.</p><ul>'
    for slug, (title, description) in DOCUMENTS.items():
        body += f'<li><a href="{slug}.html">{html.escape(title)}</a><p>{html.escape(description)}</p></li>'
    body += f'</ul><p>The brochure’s legislative snapshot is {snapshot}. Rendering this source record does not update or re-verify that snapshot.</p><p><a href="../brochure/">Brochure editions and downloads</a></p>'
    (output / 'index.html').write_text(page('Brochure sources', body), encoding='utf-8')
    section = f'''  <section aria-labelledby="references">
    <h2 id="references">Brochure sources</h2>
    <p>Read the <a href="references/sources.html">sources behind the brochure</a>,
      including the legislative record and attributed industry statements.</p>
    <p class="small mute">The brochure’s legislative snapshot is {snapshot}.
      The source record includes a Markdown download.</p>
  </section>'''
    if 'id="references"' in text:
        text, count = re.subn(r'  <section aria-labelledby="references">.*?</section>',
                              lambda _match: section, text, count=1, flags=re.S)
        if count != 1:
            raise SystemExit('Existing references section could not be updated; review the homepage manually.')
    else:
        text = text.replace(marker, section + '\n\n' + marker, 1)
    home.write_text(text, encoding='utf-8')
    print(f'Reference pages, Markdown downloads, and homepage links written to {site}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site-root', type=Path, required=True, help='Staged gh-pages root containing index.html; existing media and PDFs are preserved.')
    render(parser.parse_args().site_root.resolve())
