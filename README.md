# Snarkypuss — webdev

This is an orphan branch. It shares no history with `main` and holds the
project's published material rather than its software: the brochure and its
sources, and the artwork behind them.

It is kept separate because it has nothing to do with building or running
Snarkypuss. Someone cloning the project to install it has no use for a LaTeX
toolchain or a 10 MB cover plate, and the brochure's release cycle has nothing
to do with the software's.

## Branches

| Branch | Holds |
|---|---|
| `main` | the Snarkypuss software — MIT licensed |
| `webdev` | this branch: brochure, sources, artwork |
| `gh-pages` | the published site at snarkypuss.ca |

A `git clone` fetches every branch's objects regardless, so the separation is
about keeping the trees and histories apart, not about download size.

## Contents

```
brochure/          the 16-page A5 brochure — see brochure/README.md
```

[`brochure/README.md`](brochure/README.md) is the operative document: toolchain, build commands, the
page-marker model, edition and dating, and the artwork dimensions. Start there.

## Licensing

The brochure, the cover artwork and the Snarkypuss character are **all rights
reserved** — see `LICENSE` in this branch. They are not covered by the MIT
License that applies to the software on `main`.

Redistributing the brochure PDF complete and unmodified for non-commercial
purposes is permitted. Reusing the character in new artwork is not.

The build system itself — `brochure/tools/` and `brochure/templates/` — is MIT
licensed along with the rest of the software.
