# experiments - offline research runs

The scripts that produce the numbers in the paper: adapters for the RCAEval benchmark, the
experiment runners (E1 to E6), the statistics, and the table and figure generators.

Every run takes a `--config` YAML and writes to `results/<run_id>/` together with the config and
the environment it ran in. Nothing here is a web service. Spec: `docs/08_EXPERIMENTS_SPEC.md`.

    cd experiments && python run_c1_grounding.py --config configs/c1_re1_ob.yaml
