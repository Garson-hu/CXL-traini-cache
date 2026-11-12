# Related Work

Literature tracking for the project. Status: initial list, 2026-11-11. No paper
on this list has been read in full for this project yet.

Rules for this file:

- Do not record a claim about a paper that has not been checked against the
  paper itself. Mark anything taken from an abstract or a secondary source as
  **preliminary**.
- Fill "Key mechanism", "Evaluation workloads", and "Potential limitations"
  only after reading the paper.
- "Relationship to our project" states what we need to find out, until the
  paper has been read.

Reading status values: `not read`, `skimmed`, `read`, `read in detail`.

## Summary

| Short name | Venue / year | Topic | Reading status |
|---|---|---|---|
| NoPFS | SC 2021 | Prefetching for distributed ML training I/O | not read |
| Quiver | USENIX FAST 2020 | Storage cache for deep learning training | not read |
| DeepMemoryDL | ICPP 2022 | CXL-based memory for distributed deep learning | not read |

Bibliographic details (authors, venue, year, DOI) were checked by web search on
2026-11-11. Everything else below is preliminary.

## Entries

### NoPFS

| Field | Content |
|---|---|
| Paper | Clairvoyant Prefetching for Distributed Machine Learning I/O. N. Dryden, R. Böhringer, T. Ben-Nun, T. Hoefler. |
| Venue / year | SC '21 (International Conference for High Performance Computing, Networking, Storage and Analysis), 2021. DOI 10.1145/3458817.3476181. arXiv 2101.08734. |
| Main research problem | Preliminary (title and abstract level): I/O as a bottleneck in distributed ML training. To be confirmed on reading. |
| Key mechanism | To be filled after reading. |
| Evaluation workloads | To be filled after reading. |
| Relationship to our project | Closest known work on exploiting advance knowledge of the training access order. Find out: how future accesses are obtained, which storage tiers are used, how it treats capacity smaller than the dataset, and whether its results agree with our historical observation that prefetching hides I/O latency when storage bandwidth exceeds consumption. Candidate baseline for "prefetching". |
| Potential limitations | To be filled after reading. |
| Reading status | not read |

### Quiver

| Field | Content |
|---|---|
| Paper | Quiver: An Informed Storage Cache for Deep Learning. A. V. Kumar, M. Sivathanu. |
| Venue / year | 18th USENIX Conference on File and Storage Technologies (FAST '20), 2020, pp. 283-296. |
| Main research problem | Preliminary (title and abstract level): caching training data for deep learning jobs on a shared GPU cluster. To be confirmed on reading. |
| Key mechanism | To be filled after reading. |
| Evaluation workloads | To be filled after reading. |
| Relationship to our project | Closest known work on DL-aware cache management when the cache is smaller than the dataset and is shared by jobs. Find out: its admission and eviction approach, what it assumes about access order, how it shares cache space between jobs, and how it relates to analytical note A1 in [research_questions.md](research_questions.md). Relevant to RQ2 and RQ4. |
| Potential limitations | To be filled after reading. |
| Reading status | not read |

### DeepMemoryDL

| Field | Content |
|---|---|
| Paper | Exploiting CXL-based Memory for Distributed Deep Learning. M. Arif, K. Assogba, M. M. Rafique, S. Vazhkudai. |
| Venue / year | 51st International Conference on Parallel Processing (ICPP), 2022. DOI 10.1145/3545008.3545054. |
| Main research problem | Preliminary (title and abstract level): using CXL-based memory to address I/O bottlenecks in deep learning training. To be confirmed on reading. |
| Key mechanism | To be filled after reading. |
| Evaluation workloads | To be filled after reading. |
| Relationship to our project | Closest known prior work combining CXL memory with DL training data. Find out: whether the evaluation used real CXL hardware or emulation, which baselines it compared against (in particular DRAM caching under equal memory budgets), what cache management it uses, and what it leaves open. Essential for positioning any novelty claim. |
| Potential limitations | To be filled after reading. |
| Reading status | not read |

## Entry template

```markdown
### <Short name>

| Field | Content |
|---|---|
| Paper | |
| Venue / year | |
| Main research problem | |
| Key mechanism | |
| Evaluation workloads | |
| Relationship to our project | |
| Potential limitations | |
| Reading status | not read |
```

## Topics to search (no papers recorded yet)

- Training data caching and data-loading pipelines for deep learning.
- I/O characterization of scientific ML workloads (CosmoFlow, MLPerf HPC).
- CXL memory performance characterization and tiering.
- Cache replacement with known future access order.
