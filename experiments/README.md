# experiments - offline research runs

The scripts that produce the numbers in the paper: adapters for the RCAEval benchmark, the
experiment runners (E1 to E6), the statistics, and the table and figure generators.

Every run takes a `--config` YAML and writes to `results/<run_id>/` together with the config and
the environment it ran in. Nothing here is a web service. Spec: `docs/08_EXPERIMENTS_SPEC.md`.

    cd experiments && python run_c1_grounding.py --config configs/c1_re1_ob.yaml

## Two environments, and which script needs which

RCAEval pins numpy 1.x and the analyzer uses 2.x, so they cannot share an environment. Almost
everything here runs in the analyzer's (`analyzer/.venv`), because the adapter reads the benchmark's
CSV files with pandas and never imports RCAEval. Only two scripts need `.venv-rcaeval`:
`download_rcaeval.py` and `run_rcaeval_baselines.py`. Both say so if run with the wrong one.

Setting the RCAEval environment up is in `docs/08_EXPERIMENTS_SPEC.md` section 2. It carries no
torch and no tensorflow, which hard rule 1 forbids.

## E1 - explanation grounding on all of RE1 (M3)

One system at a time, then pool, then build the tables and figure from the pooled summaries:

    analyzer/.venv/Scripts/python.exe experiments/run_c1_grounding.py --config experiments/configs/c1_re1_ob.yaml
    analyzer/.venv/Scripts/python.exe experiments/run_c1_grounding.py --config experiments/configs/c1_re1_ss.yaml
    analyzer/.venv/Scripts/python.exe experiments/run_c1_grounding.py --config experiments/configs/c1_re1_tt.yaml
    analyzer/.venv/Scripts/python.exe experiments/run_c1_grounding.py --config experiments/configs/c1_re1.yaml
    analyzer/.venv/Scripts/python.exe experiments/make_tables.py
    analyzer/.venv/Scripts/python.exe experiments/make_figures.py

Each per-system run needs that system downloaded (`download_rcaeval.py --dataset RE1-SS`, ...).
`make_tables.py` and `make_figures.py` read only the committed `summary*.csv` files, so they work
on a fresh clone. Findings: `paper/notes/E1_findings.md`.

## M2.4 - reproducing RCAEval's own baselines

Two steps, one per environment. The first records what their code ranked; the second scores it,
runs ours, and attributes the difference one cause at a time.

    experiments/.venv-rcaeval/Scripts/python.exe experiments/run_rcaeval_baselines.py
    analyzer/.venv/Scripts/python.exe experiments/run_m24_compare.py

Results land in `results/m2_4/`, with `comparison.txt` holding the printed tables.
