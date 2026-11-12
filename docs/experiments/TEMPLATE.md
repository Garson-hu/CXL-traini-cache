# <Experiment ID>: <Title>

<!--
Copy this file to docs/experiments/<experiment_id>.md.
Experiment IDs follow E<NNN>-<short-name> and are never reused.
Do not report a number that was not produced by this experiment without saying where it comes from.
Keep negative and inconclusive results. Do not delete a report because the result was disappointing.
-->

## 1. Experiment metadata

| Field | Value |
|---|---|
| Experiment ID | |
| Date / timestamp (start, end) | |
| Author | |
| Status | planned / running / completed / failed / invalidated |
| Result type | real hardware / simulation / analytical |
| Git commit | |
| Working tree clean at run time | yes / no |
| Hostname | |
| Hardware reference | `hardware/<host>.md` |
| Random seed(s) | |
| Raw result location | `$CXL_TRAINING_DATA_ROOT/results/<experiment_id>/` |
| Summary location | `experimental_results/<experiment_id>/` |
| Related research question(s) | |

## 2. Motivation

Why this experiment is needed and which decision depends on it.

## 3. Hypothesis

The specific, falsifiable expectation, written before the experiment is run.
State what outcome would refute it.

## 4. Setup

### Hardware environment

Machine, CPU, memory configuration, CXL configuration, GPU, storage. Reference
the hardware file and list anything that differs from it.

### Software environment

OS, kernel, framework and library versions, workload version or commit.

### Configuration

Workload, dataset (name, size, number of files, location), cache capacity,
resource budgets, parameters. Reference the config file under `configs/`.

## 5. Baselines

What the result is compared against and why each baseline is a fair, strong
comparison. Include the simplest reasonable alternative.

## 6. Methodology

Procedure, number of runs, warm-up handling, cache state before each run, how
each metric is measured, and how interference from other users was handled.

## 7. Results

Tables and figures with units. State the number of runs and the variation
between them. Report only what was measured in this experiment.

## 8. Analysis

Interpretation of the results. Does the outcome support or refute the
hypothesis? Separate what the data shows from what is inferred.

## 9. Limitations

What this experiment does not show. Threats to validity, confounders,
restrictions of the hardware or workload, and anything that was not verified.

## 10. Conclusions

The takeaways in a few sentences, and what follows for the next step or for
the research questions.

## 11. Reproduction instructions

Exact commands, environment setup, configuration files, and expected run time.
Someone else should be able to repeat the experiment from this section alone.
