#!/usr/bin/env bash
# Rebuild the report figures from committed data, then compile the PDF.
# Needs the backend virtualenv (backend/.venv) and a TeX installation with xelatex and biber.
set -euo pipefail
cd "$(dirname "$0")"
../backend/.venv/bin/python figures/make_figures.py
latexmk -xelatex -interaction=nonstopmode -halt-on-error hipparchus_scientific_report.tex
