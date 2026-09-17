## Licensing

This project is licensed in two parts.

**The software is AGPL-3.0.** That covers the Snarkypuss gateway software,
SnarkyCtl, the installation and configuration tooling, and the brochure build
system under `brochure/tools/` and `brochure/templates/`. The full text is in
`LICENSE`.

The AGPL permits use, modification, redistribution and sale. What it asks in
return is reciprocity: if you distribute a modified Snarkypuss, or run one as
a service other people use, you must offer your users the source under the
same licence. That second clause is the reason for AGPL rather than GPL —
Snarkypuss is server software, and someone could otherwise run a modified
version as a hosted service without ever distributing anything.

In short: build on it, fork it, charge for it if you like. You cannot close it.

**The artwork, song, video and brochure are all rights reserved.** They are not
open source and not covered by the AGPL:

| Branch | Holds |
|---|---|
| `webdev` | the brochure, its diagrams, and the cover artwork |
| `gh-pages` | the published site, the promotional song and video |

Each carries its own `LICENSE`. The brochure build system under
`brochure/tools/` and `brochure/templates/` is part of the software and stays
AGPL licensed wherever it appears.

Two things are permitted without asking: redistributing the brochure PDF
complete and unmodified for non-commercial purposes, and linking to or
embedding the published video. Anything else — reusing the character in new
artwork, remixing the song, altering the brochure — needs written permission.

The character is reserved deliberately rather than by oversight. Snarkypuss is
a privacy tool, and artwork bearing the character should continue to indicate
*this* project rather than something else wearing the same face. The software
carries no such constraint: fork it, rename it, ship your own.

> GitHub reads the `LICENSE` from the default branch only. It does not look at
> other branches. This section, `NOTICE`, and the per-branch licence files are
> the authoritative statement.
