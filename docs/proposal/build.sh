#!/usr/bin/env bash
# Build the proposal PDFs. Needs XeLaTeX + Noto CJK fonts (TeX Live 2023+ with fonts-noto-cjk).
#   main.tex      full version  -> VGHTC-Queue-Agent-Proposal.pdf
#   main-lean.tex lean version  -> VGHTC-Queue-Agent-Proposal-lean.pdf
set -euo pipefail
cd "$(dirname "$0")"
for f in main main-lean; do xelatex -interaction=nonstopmode $f.tex >/dev/null; done
for f in main main-lean; do xelatex -interaction=nonstopmode $f.tex >/dev/null; done
cp main.pdf VGHTC-Queue-Agent-Proposal.pdf
cp main-lean.pdf VGHTC-Queue-Agent-Proposal-lean.pdf
for f in main main-lean; do echo "built $f.pdf ($(pdfinfo $f.pdf | awk '/Pages/{print $2}') pages)"; done
