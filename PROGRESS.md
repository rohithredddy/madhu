# PROGRESS.md - Running log

Update this file at the end of every task. Newest entry at the top of "Log".
Human: read this before every session to know where things stand.

## Current status
- Current milestone: M0
- Next task: M0.1 (then M0.3 in the same commit), then M1.1 onward
- Blockers: none for M0.1. Before M1.1 we need Python 3.10 installed (`uv python install 3.10`)
  and a project virtual environment; see "Environment" for why 3.14 will not work.

## Environment (measured 2026-10-03)

Everything below was read off this machine, not assumed.

| Thing | Status |
|---|---|
| OS | Windows 11 Home Single Language, 10.0.26200 |
| CPU | 12th Gen Intel Core i5-1235U, 10 cores / 12 threads (no GPU used) |
| RAM | 15.7 GB total |
| Disk C: | **11.7 GB free of 237.7 GB - the tightest resource we have** |
| Java | 21.0.12.1 LTS (Oracle), `C:\Program Files\Java\jdk-21.0.12.1`; `javac` 21.0.12.1 |
| JAVA_HOME | set to the path above on 2026-10-03 (it was empty) |
| Maven | **not installed, and deliberately not going to be** - we use the Maven Wrapper, see decision 18 |
| Python | 3.14.4 only, at `C:\Users\hp\AppData\Local\Programs\Python\Python314`. **3.10 is not installed yet and is required** |
| uv | 0.11.20 - this is how Python 3.10 will be installed (`uv python install 3.10`) |
| Node / npm | 24.15.0 / 11.12.1 |
| Git | 2.54.0.windows.1 |

Python packages in the global 3.14 environment: `numpy 2.4.4`, `scipy 1.17.1`, `pyyaml`, `joblib`,
`pytest`, `fastapi`, `uvicorn`, `pydantic` are present; **`pandas`, `scikit-learn`, `shap`,
`lightgbm`, `ruptures`, `networkx`, `statsmodels`, `matplotlib`, `pyarrow` are missing**. That
environment also holds ~190 unrelated packages (pipecat, google-genai, openai, playwright, boto3),
so the project will use its own virtual environment regardless.

Why Python 3.14 cannot be used for `analyzer/` (checked against PyPI, not guessed):
- `ruptures` 1.1.10 declares `requires_python = <3.14,>=3.9` and ships Windows wheels for cp39-cp313
  only. There is no cp314 wheel. Change-point detection is core to PARE.
- `shap` 0.52.0 needs >= 3.12, but its only 3.14 artifact is a `cp314t` (free-threaded) manylinux
  wheel. There is no Windows cp314 wheel.
- `dowhy` also caps at `<3.14`.

The whole stack does resolve cleanly for Python 3.10 on Windows (checked with
`uv pip compile --python-version 3.10 --python-platform windows`): numpy 2.2.6, pandas 2.3.3,
scikit-learn 1.7.2, scipy 1.15.3, shap 0.49.1, lightgbm 4.7.0, ruptures 1.1.10, networkx 3.4.2,
statsmodels 0.15.0, matplotlib 3.10.9, pyarrow 25.0.1, fastapi 0.142.2, uvicorn 0.54.0,
pydantic 2.13.5, pytest 9.1.1. So pip picks the last 3.10-compatible versions by itself and no
pinning work is needed.

## Open questions (for the human)

1. **RCAEval pulls PyTorch. Does hard rule 1 allow it inside the isolated venv?**
   `pip install RCAEval` installs nothing by itself: all 414 dependencies sit behind extras
   (`default` 164, `rcd` 170, `eventadl` 80), so the real install is `RCAEval[default]`, and that
   extra requires `torch>=1.12.1`, plus `numpy<2` and `networkx==2.5` for Python < 3.13.
   - This confirms the separate-venv instruction in `PROJECT_RULES.md` section 4 and
     `08_EXPERIMENTS_SPEC.md` section 2 is mandatory, not optional: `numpy<2` and `networkx==2.5`
     cannot coexist with our resolved stack (numpy 2.2.6, networkx 3.4.2).
   - But hard rule 1 says "No PyTorch/TensorFlow". Reproducing their baselines (M2.4, M4.2) means
     torch lands in `experiments/.venv-rcaeval`, roughly 200-800 MB of wheels.
   - Proposed reading: the rule is about **our** method, which stays scikit-learn only; torch is
     allowed in the isolated baseline venv and nowhere else. Needs the human's yes before M2.
   - Not blocking anything before M2.

2. **Disk space.** 11.7 GB free. Maven's `~/.m2` (300-500 MB once Spring Boot, JPA, H2 and springdoc
   are pulled), the two Python venvs, torch, and the RCAEval RE1/RE2/RE3 downloads all land on C:.
   RE2 and RE3 carry logs and traces and are the big ones. Worth freeing space or planning to keep
   only one RCAEval system on disk at a time (which `08_EXPERIMENTS_SPEC.md` section 2 already
   suggests for memory reasons).

The 16 points raised in the first spec review were all answered on 2026-10-03 and are recorded
under "Decisions made" below.

## Decisions made

All of these came from the human's answers to the first spec review (2026-10-03) and are already
written into the spec files. One line of reason each.

### Contradictions between docs

1. **Symptom direction is "ancestor / caller of the true root cause".**
   Reason: edges run caller -> callee, so a fault travels from the called service up to its callers;
   the affected services are therefore ancestors, not descendants. `00_RESEARCH_PLAN.md` section 8.2
   said "downstream" and was wrong; the other four docs were already right.

2. **The Java fallback engine is called `NSIGMA_JAVA_FALLBACK` everywhere**, including the
   `/api/engines` list, which used to say `NSIGMA_JAVA`.
   Reason: the name is shown in the UI and stored in the database, so two spellings would mean two
   apparent engines.

3. **Change point = `ruptures.Binseg(model="l2")`, one change point.** PELT and Bayesian online CPD
   are optional ablations only.
   Reason: one implementation, named in one place (`05` section 3 step 2). `00` section 6 promised
   PELT and now points at the real choice. The PELT citation stays in the reference list.

4. **`noise` is the string `LOW` / `MEDIUM` / `HIGH` on the API and in the UI**; the FastAPI service
   layer maps it to the float the library wants (0.5 / 1.0 / 2.0) before calling
   `make_case(noise=float)`.
   Reason: the UI needs discrete labelled choices, the library needs a number, and exactly one place
   should know the mapping. Documented in `05` section 5 and `06` section 3.

5. **`faultType` is UPPERCASE in all JSON and in `meta.json`.** Synthetic: `LATENCY`, `CPU`, `MEM`,
   `ERROR`. RCAEval: the dataset's own names uppercased (`CPU`, `MEM`, `DISK`, `DELAY`, `LOSS`, plus
   the RE3 code-level names). The Python library may stay lowercase internally; the service layer
   converts.
   Reason: `meta.json` already used `MEM` while the synthetic request used `latency`, so the same
   field had two casings. Also made the library name consistent: `fault="mem"`, not `"memory"`.

6. **`HOW_TO_USE_THIS_KIT.md` will not exist.** The references in `PROJECT_RULES.md` and `README.md` are
   removed.
   Reason: two docs pointed at a file that was never written; deleting the pointer is simpler than
   inventing a fourth overview document.

### Ambiguities that needed a ruling

7. **`NSIGMA` (Python) and `NSIGMA_JAVA_FALLBACK` never use the change point.** Their abnormal
   window is `[alarmTime, end of recent]` on both sides.
   Reason: two reasons, both important. The shared-sample agreement test in `03` section 4.4 is only
   possible if both sides use the same window; and the delay-robustness claim (RQ4) is about what
   change-point re-anchoring adds, so the baselines must feel the full cost of a late alarm. The same
   rule applies to the explainer baselines (`SHAP_IFOREST`, `ECDF`, `PCA_RECON`).

8. **`inheritedFraction` is computed on one scale, in raw metric units:**
   `marginal_dev = |median(abnormal) - median(normal)|`,
   `self_dev = |median(abnormal residual) - median(normal residual)|`,
   `inheritedFraction = clip(1 - self_dev / marginal_dev, 0, 1)`, and 0 when `marginal_dev == 0`.
   `selfScore` stays normalised by the residual MAD, because that is the ranking score. The symptom
   template now reads "about X% of this change is explained by {explainedBy}".
   Reason: the old formula divided a residual-MAD score by a raw-MAD score. That is not a ratio of
   like quantities, so the "fraction" could leave [0, 1] - and the UI prints it as a percentage.

9. **There is now a "nothing clearly wrong" outcome.** New `PareConfig.min_cause_score = 3.0` and a
   new response field `verdict` (`ROOT_CAUSE_FOUND` | `NO_CLEAR_CAUSE`). If the top service score is
   below the threshold the verdict is `NO_CLEAR_CAUSE` and **no service gets the role `CAUSE`**.
   Roles are assigned in strict precedence order: CAUSE (rank 1, only when the verdict is
   `ROOT_CAUSE_FOUND`) > SYMPTOM > ALSO_ABNORMAL > NORMAL. Java headline for that case:
   "No clear root cause found. The strongest signal is {service} ({score})."
   Reason: the old spec made rank 1 `CAUSE` unconditionally, so analysing a quiet window produced a
   confident accusation. The precedence order also removes the old overlap where a service satisfied
   both the SYMPTOM and the ALSO_ABNORMAL condition. `verdict` is stored as its own database column
   so reports can count these without parsing JSON.

10. **`PARE_LGBM` has a task: new M1.7b** ("PARE_LGBM engine (LightGBM dependency model) + test").
    Reason: the engine was in the `05` engine table and in experiment E2 but no task built it, so it
    would have been missed.

11. **The replay detector must not use `injectTime`.** Baseline = the first
    `app.replay.baseline-rows` rows of the case (new config key, default 300, replacing
    `baseline-min-rows: 60`). `injectTime` is used in the catalog only, to mark a case
    `replayable` when the injection happens after those baseline rows.
    One-click analyze and the offline experiments still split the normal window at
    `injectTime - normalGapSeconds`. This is the standard RCAEval protocol, applied identically to
    every method, and it is now written down as an explicit stated assumption in `03` section 4.2
    and `08` section 4, together with the E3 variant that avoids `inject_time` entirely.
    Reason: the live demo should be honest about detection - a real detector does not know when the
    fault starts. Offline scoring follows the benchmark so our numbers stay comparable with
    published ones. A unit test asserts the detector takes no `injectTime` argument at all, so the
    rule cannot be broken by accident later.

12. **`app.data-dir` comes from the environment variable `XAIRCA_DATA_DIR`**, default
    `${user.dir}/../data`, resolved to an absolute path at startup and logged on one line. The H2
    URL is built from it. Tests use in-memory H2 (`jdbc:h2:mem:`) and a temporary data dir. The
    `start-all` scripts `cd` into `backend/` first.
    Reason: the old literal `jdbc:h2:file:../data/db/xairca` only resolved correctly when Java was
    launched from `backend/`, and a wrong working directory would silently create a second empty
    database somewhere else.

### Minor

13. **`faithfulness_auc` removed from `cases.csv`.** E5 writes its own `faithfulness.csv` and
    `stability.csv` in the same run folder, with columns defined in `06` section 5. `cases.csv`
    gains a `verdict` column instead.
    Reason: the faithfulness data has a different shape (one row per case, method and k), so it was
    always going to be an empty column for every other experiment.

14. **`params.topK` (default 10) = how many indicators the response returns.** It is separate from
    `cp_top_k` (default 5), which is how many columns the change-point step inspects. Both are in
    the new PareConfig table in `05` section 1.1.
    Reason: the two were easy to confuse, and the example request said `topK: 5` while the UI shows
    a top-10 table.

15. **All windows are defined once, in a table in `05` section 3 step 2.** One-click analyze sends
    `recent = [alarm - 300 s, alarm + 120 s]`; change-point search is
    `[alarm - 300 s, alarm + min(60 s, available data)]`; analysis window is
    `[changePoint, changePoint + 120 s]`, cut to available data; replay sends only played rows.
    `03` and `08` refer to that table instead of repeating the numbers.
    Reason: the numbers appeared in three docs with slightly different wording (notably
    `cp_lookahead` 0 versus `recent-after-seconds` 120), which is how the two sides drift apart.

16. **No README inside `data/`.** The `data/` layout is described in the root `README.md`.
    Reason: `data/` is git-ignored, so a README there would never be committed. M0.1 was changed to
    say so explicitly.

### Build tooling

18. **Java builds use the Maven Wrapper (`./mvnw`), not a system Maven.** Maven is not installed on
    this machine and will not be: it is also not available through winget (only unrelated packages
    match `Apache.Maven`). The Spring Initializr zip already contains `mvnw`, `mvnw.cmd` and
    `.mvn/wrapper/maven-wrapper.properties`, and all three get committed. `PROJECT_RULES.md` section 6,
    `docs/02` section 4 and the definition of done now say `./mvnw`.
    Reason: the wrapper pins the exact Maven version in a committed file, which is what hard rule 10
    (reproducible) asks for, and it needs nothing on the machine but the JDK. It also avoids editing
    the user PATH.
    Consequence to remember at M8.1: the wrapper cannot be created with `mvn wrapper:wrapper`,
    because that needs the Maven we do not have. M8.1 must start from the Spring Initializr zip.
    Also done at the same time: `JAVA_HOME` was empty and is now set to
    `C:\Program Files\Java\jdk-21.0.12.1` (user-level), because some IDE Java tooling expects it
    even though the wrapper copes without it.

### Order of work

17. **Normal order: research first.** M0 -> M1 -> M2 ... The "application early" shortcut in
    `07_TASKS.md` is not taken.
    Reason (the human's): if the synthetic check in M1.10 or the first RE1 results in M3 do not
    support the cause-versus-symptom story, we need to know that **before** building an application
    around it. So M1.10 and M3.2 are explicit stop-and-report gates.

## Things the human must check by hand
- Static call graphs in experiments/graphs/*.yaml (M2.5)
- Ground-truth indicator mapping for RCAEval (M2.2)
- Whether the M1.10 synthetic check supports the cause-versus-symptom story (gate before M2)
- Whether the first RE1 results in M3.2 support it on real data (gate before the application track)

## Log
<!-- Template for each entry:
### YYYY-MM-DD - Task Mx.y - short title
- What was done:
- How it was tested (commands + result):
- Files changed:
- Left open / next:
-->

### 2026-10-03 - Environment check and build tooling - no code yet
- What was done: checked every requirement in `PROJECT_RULES.md` section 4 against the actual machine and
  recorded the result in "Environment" above. Java 21, Node 24.15.0, npm 11.12.1, git and uv are all
  present and fine. Three gaps found: Maven missing, Python 3.10 missing (only 3.14, which this stack
  cannot use), and the Python libraries not installed. Decided on the Maven Wrapper instead of a
  system Maven (decision 18) and set `JAVA_HOME`, which was empty. Two findings need the human and
  are written up under "Open questions": RCAEval's `default` extra requires PyTorch, and the disk has
  only 11.7 GB free.
- How it was tested (commands + result):
  - `java -version` / `javac -version` -> 21.0.12.1 LTS; `node -v` -> v24.15.0; `npm -v` -> 11.12.1;
    `git --version` -> 2.54.0; `uv --version` -> 0.11.20.
  - `mvn -v` -> not found. Confirmed it is genuinely absent, not a stale PATH: no `mvn.cmd` anywhere
    under `C:\`, Program Files, the user profile, LocalAppData or ProgramData; no `MAVEN_HOME` or
    `M2_HOME`; the live registry PATH (machine and user) contains only the Oracle javapath entry.
    `winget search Apache.Maven` -> no package.
  - `py -0p` -> only 3.14 present; `py -3.10 --version` -> no suitable runtime.
  - Package presence checked with `importlib.util.find_spec` in the 3.14 environment: pandas,
    sklearn, shap, lightgbm, ruptures, networkx, statsmodels, matplotlib, pyarrow all missing.
  - 3.14 incompatibility verified from PyPI metadata and wheel filenames, not from memory: ruptures
    1.1.10 is capped `<3.14` with Windows wheels only up to cp313; shap 0.52.0 has no Windows cp314
    wheel; dowhy is capped `<3.14`.
  - `uv pip compile --python-version 3.10 --python-platform windows` on the full stack -> resolves
    cleanly; the chosen versions are listed in "Environment".
  - RCAEval metadata read from PyPI: 414 `requires_dist` entries, all behind the extras
    `default` / `rcd` / `eventadl`; `default` requires `torch>=1.12.1`, `numpy<2`, `networkx==2.5`.
  - `setx JAVA_HOME "C:\Program Files\Java\jdk-21.0.12.1"` -> verified by reading it back from
    `HKCU:\Environment` and confirming `bin\java.exe` exists at that path.
  - Nothing was installed. All of the above was read-only apart from setting `JAVA_HOME`.
- Files changed: `PROJECT_RULES.md` (section 6 and definition of done now use `./mvnw`),
  `docs/02_ARCHITECTURE.md` (run command), `docs/03_JAVA_BACKEND_SPEC.md` (section 1 explains the
  wrapper and the M8.1 ordering constraint), `PROGRESS.md`.
- Left open / next: the human's answer on the PyTorch question (not needed until M2) and on disk
  space. Then `uv python install 3.10`, the `analyzer/` virtual environment, and M0.1 + M0.3.

### 2026-10-03 - Spec fixes after first review - no code yet
- What was done: read `PROJECT_RULES.md`, `PROGRESS.md` and all nine files in `docs/`, reported 6
  contradictions, 7 ambiguities and 4 smaller problems, and applied the human's rulings to the
  specs. All 17 decisions are written up under "Decisions made" above. Changes by file:
  - `PROJECT_RULES.md`, `README.md`: dropped the `HOW_TO_USE_THIS_KIT.md` references; the root README now
    describes the `data/` layout and the `XAIRCA_DATA_DIR` variable.
  - `docs/00_RESEARCH_PLAN.md`: symptom rate reworded to "ancestor (caller)"; PELT replaced by
    Binseg as the implementation, PELT kept as an optional ablation.
  - `docs/02_ARCHITECTURE.md`: replay baseline no longer described as "before the fault"; data
    folder list extended.
  - `docs/03_JAVA_BACKEND_SPEC.md`: env-var data dir and derived H2 URL; `baseline-rows: 300`
    replacing `baseline-min-rows: 60`; detector no longer sees `injectTime`; `replayable` flag;
    stated assumption about the normal window; fallback window and verdict; `NO_CLEAR_CAUSE`
    headline; symptom template wording; `verdict` entity column; `NSIGMA_JAVA_FALLBACK` in
    `/api/engines`; in-memory H2 for tests.
  - `docs/04_REACT_FRONTEND_SPEC.md`: `NO_CLEAR_CAUSE` presentation (grey, no red, no cause
    sentences); UPPERCASE fault types and noise levels in the lab.
  - `docs/05_PYTHON_ANALYZER_SPEC.md`: new PareConfig parameter table (section 1.1); the one window
    table; raw-unit `inheritedFraction`; verdict and strict role precedence; NSIGMA window rule;
    noise and fault-name conversion at the service layer; two new tests.
  - `docs/06_DATA_CONTRACTS.md`: UPPERCASE enum rule; `verdict` in the response; `topK` 10 and its
    difference from `cpTopK`; uppercase synthetic request example; `faithfulness_auc` replaced by
    `verdict` in `cases.csv` plus the new `faithfulness.csv` / `stability.csv` schemas.
  - `docs/07_TASKS.md`: new M1.7b for `PARE_LGBM`; M1.7 now covers verdict and role precedence;
    M0.1 says no README in `data/`.
  - `docs/08_EXPERIMENTS_SPEC.md`: stated assumption about `inject_time` with the E3 no-`inject_time`
    variant; E5 writes its own files; noise levels uppercased.
- How it was tested: documentation only, so no build. Each edit was applied by a script that
  requires an exact unique match for every replacement and fails otherwise, so no edit landed in the
  wrong place. Afterwards `grep` confirmed zero remaining occurrences of `HOW_TO_USE`,
  `faithfulness_auc`, `baseline-min-rows`, bare `NSIGMA_JAVA`, `"noise": "medium"`,
  `"faultType": "latency"` and the old "downstream service" wording, and that `verdict` /
  `NO_CLEAR_CAUSE` now appear in all five docs that need them. Config key names (`cp_lookback_s`)
  were made consistent across `03`, `05` and `08`.
- Files changed: `PROJECT_RULES.md`, `README.md`, `PROGRESS.md`, `docs/00` through `docs/08` (all except
  `docs/01_PROJECT_OVERVIEW.md`, which needed nothing).
- Left open / next: M0.1 (create the folder skeleton with short READMEs, no README in `data/`) and
  M0.3 (fill in the Environment block) in one commit, then M1.1. No code written yet.
