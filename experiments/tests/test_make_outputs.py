"""Tests for `make_tables.py` and `make_figures.py`.

The property that matters is hard rule 2: a number in a table must be a number in
a result file. The generators read the committed summary files, so these tests run
on a fresh clone without the benchmark data.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

from experiments import make_figures, make_tables

E1 = Path(__file__).resolve().parents[1] / "results" / "e1_re1"
HAVE_E1 = (E1 / "summary_by_system_fault.csv").exists()

needs_e1 = pytest.mark.skipif(not HAVE_E1, reason="run configs/c1_re1.yaml first")


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\b\d+\.\d{3}\b", text))


@needs_e1
def test_every_number_in_table2_comes_from_the_summary_files():
    """Except the Gap column, which is a stated subtraction of two numbers that
    are themselves in the table."""
    table = make_tables.table2_grounding(E1)
    gap_column = table.header.index("Gap")
    in_table = {cell for row in table.rows for i, cell in enumerate(row)
                if i != gap_column and re.fullmatch(r"\d+\.\d{3}", cell)}
    source = "".join(
        pd.read_csv(E1 / name).to_csv(float_format="%.3f")
        for name in ("summary.csv", "summary_by_system.csv")
    )
    assert in_table and in_table <= _numbers(source)


@needs_e1
def test_the_gap_compares_service_and_metric_accuracy_on_the_same_cases():
    """The gap is AC@1 on the CPU and MEM cases minus ExpAC@1, which covers only
    those cases - not AC@1 over every fault type, as M3.1 first reported it."""
    table = make_tables.table2_grounding(E1)
    header = table.header
    for row in table.rows:
        if row[1] == "":
            continue
        strict_ac1 = float(row[header.index("AC@1, CPU+MEM")])
        exp_ac1 = float(row[header.index("ExpAC@1")])
        assert float(row[header.index("Gap")]) == pytest.approx(strict_ac1 - exp_ac1, abs=2e-3)


@needs_e1
def test_a_missing_symptom_rate_is_an_empty_cell_not_zero():
    """Train Ticket has no graph. A 0.000 there would read as "never blamed a
    victim" when the question could not be asked."""
    table = make_tables.table2_grounding(E1)
    header = table.header
    start = next(i for i, row in enumerate(table.rows) if row[0].startswith("Train Ticket"))
    for row in table.rows[start + 1:]:
        assert row[header.index("Symptom rate")] == ""


@needs_e1
def test_the_loose_table_carries_the_acceptable_set_size_on_every_row():
    table = make_tables.table2b_loose(E1)
    for row in table.rows:
        if row[1] != "":
            assert row[1].isdigit(), row


@needs_e1
def test_both_formats_are_written(tmp_path: Path):
    assert make_tables.main(["--e1", str(E1), "--out", str(tmp_path)]) == 0
    for name in make_tables.TABLES:
        markdown = (tmp_path / f"{name}.md").read_text(encoding="utf-8")
        latex = (tmp_path / f"{name}.tex").read_text(encoding="utf-8")
        assert "Do not edit by hand" in markdown
        assert "\\begin{tabular}" in latex and "\\end{table}" in latex
        # Underscores in engine names would break LaTeX unescaped.
        assert "SHAP_IFOREST" not in latex.replace("SHAP\\_IFOREST", "")


def test_latex_special_characters_are_escaped():
    assert make_tables._tex("PARE_NO_RESIDUAL & 50%") == "PARE\\_NO\\_RESIDUAL \\& 50\\%"


@needs_e1
def test_figure3_is_written_as_png_and_pdf(tmp_path: Path):
    paths = make_figures.figure3_symptom_rate(E1, tmp_path)
    assert {path.suffix for path in paths} == {".png", ".pdf"}
    assert all(path.stat().st_size > 1000 for path in paths)
