#!/usr/bin/env python3
"""
CV PDF builder wrapper.

This module provides the stable function that `apply.py` should call to generate
the CV PDF using the current ReportLab template style.
"""

from __future__ import annotations

from pathlib import Path

from generate_cv_pdf import render_cv_pdf


def build_cv_pdf(markdown: str, output_path: str | Path) -> None:
    """
    Generate CV PDF (A4) from markdown text.

    Requirements covered by the underlying template:
    - Navy/green palette
    - Green left-bar section headers
    - Skills table with 32mm label column
    - Languages inline
    - No hyphenation
    - Centered 3-line contact header (excluding name)
    """
    render_cv_pdf(markdown, Path(output_path))

