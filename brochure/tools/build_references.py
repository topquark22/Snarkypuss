#!/usr/bin/env python3
"""Generate the brochure source record under build/references (requires Pandoc)."""
import html
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'build' / 'references'


def render(edition):
    """Build local HTML and Markdown artifacts from the source record only."""
    if not shutil.which('pandoc'):
        raise RuntimeError('Pandoc is required to build the sources pages; install pandoc.')
    source = (ROOT / 'references' / 'sources.md').read_text(encoding='utf-8')
    fragment = subprocess.run(
        ['pandoc', '--from=markdown+autolink_bare_uris', '--to=html5', '--wrap=none'],
        input=source, text=True, capture_output=True, check=True).stdout
    fragment = fragment.replace(
        '<table>', '<div class="table-scroll" role="region" aria-label="Source table" tabindex="0"><table>'
    ).replace('</table>', '</table></div>')
    site = html.escape(edition['site_url'], quote=True)
    snapshot = html.escape(edition['snapshot_text'])
    nav = (f'<nav aria-label="Source navigation"><a href="{site}/">Home</a> · '
           '<a href="./">Sources index</a> · <a href="sources.html">Source record</a></nav>')

    def page(title, body):
        return ('<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
                f'<title>{html.escape(title)} — Snarkypuss</title>\n'
                '<link rel="stylesheet" href="references.css">\n</head>\n'
                f'<body><div class="wrap">{nav}<main>{body}</main>'
                '<footer>Snarkypuss · Source dates are stated in the source record.</footer>'
                '</div></body>\n</html>\n')

    index = ('<h1>Brochure sources</h1><p>Read the evidence behind the brochure’s '
             'legislative and industry claims.</p><ul><li><a href="sources.html">'
             'Source record</a></li><li><a href="sources.md" download>Download Markdown</a></li></ul>'
             f'<p>The brochure’s legislative snapshot is {snapshot}. Rendering these pages '
             'does not update or re-verify the snapshot.</p>'
             f'<p><a href="{site}/brochure/">Brochure editions and downloads</a></p>')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / 'index.html').write_text(page('Brochure sources', index), encoding='utf-8')
    (OUTPUT / 'sources.html').write_text(page('Source record',
        '<p><a href="sources.md" download>Download Markdown</a></p>'
        f'<article>{fragment}</article>'), encoding='utf-8')
    (OUTPUT / 'sources.md').write_text(source, encoding='utf-8')
    (OUTPUT / 'references.css').write_text(
        (ROOT / 'templates' / 'references.css').read_text(encoding='utf-8'), encoding='utf-8')
    print(f'Built local sources pages: {OUTPUT}')


if __name__ == '__main__':
    from build import read_edition
    try:
        render(read_edition())
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc)) from exc
