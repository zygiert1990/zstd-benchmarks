---
name: compare-benchmark-results
description: Compare the JMH, GC allocation, native-memory sampling, and flamegraph artifacts stored in one docs benchmark directory in this repository, and write its Markdown comparison report.
---

# Compare benchmark results

Analyze exactly one `docs/<BenchmarkName>/` directory per request. Read the repository root `readme.md` for commands, `docs/readme.md` for shared JVM and benchmark-host metadata, and the selected directory's `readme.md` for implementation and workload metadata.

Use `scripts/compare_benchmarks.py docs/<BenchmarkName>` to parse the result triples and create or update the minimal JDK 25 chart report. Review the generated charts against the source files before finishing; do not merely trust that parsing succeeded.

## Expected inputs

Each `jdk-*` child contains one directory per implementation prefix in the runner layout:

- `<prefix>/results.txt`: the full JMH result with `-prof gc`
- `<prefix>/chunk-<size>/summary-nativemem.txt`: one async-profiler native-allocation summary per profiled chunk size
- `<prefix>/chunk-<size>/flame-cpu-forward.html`: one CPU flamegraph per profiled chunk size

Expect one `orig` triple for JDK 11. Expect `orig` (JNI) and zero or more other prefixes for JDK 25. Discover prefixes from files instead of assuming names such as `ffm` or `ffm-arena`. Report missing or ambiguous members of a triple and do not silently compare partial data.

The selected benchmark's `readme.md` must map `orig` to the tested zstd-jni version and every non-`orig` prefix to a Markdown link for its GitHub branch. The chart report shows the `orig` version as plain text and links each other implementation to its branch. Fail generation when metadata for a compared prefix is missing or ambiguous.

When the benchmark `readme.md` contains a `Test file to compress has … bytes` entry, include that input size in the chart report. Preserve JMH parameter names in workload labels. Render `chunkSize` values explicitly in bytes so, for example, `chunkSize=1 byte` cannot be mistaken for a variant or ordinal.

Require `docs/readme.md` to record the shared benchmark host's OS, architecture, CPU model, physical/logical core counts, and installed RAM using the `Benchmark host …` fields consumed by the helper. Copy this recorded metadata into each chart report. Never detect the report-generation host because it may differ from the machine that produced the benchmark results.

## Comparison rules

- Compare every common JMH benchmark and parameter combination. Keep distinct parameter sets as distinct rows.
- Interpret JMH modes correctly: lower is better for `avgt`, `sample`, and `ss`; higher is better for `thrpt`.
- Use `gc.alloc.rate.norm` (`B/op`) for on-heap allocation. Do not use `gc.alloc.rate` to rank memory efficiency because it depends on execution speed.
- Produce an all-JDK comparison using JDK 11 `orig` as its percentage baseline. Also produce a separate JDK 25-only comparison using JDK 25 `orig` as its baseline. If a required `orig` result is absent, state and use the first naturally sorted variant in that comparison.
- Express performance delta as speedup relative to baseline, so positive percentages are better. For `avgt`, speedup is `(baseline / value - 1) * 100`; for `thrpt`, it is `(value / baseline - 1) * 100`.
- Express heap and native allocation delta as savings relative to baseline: `(baseline - value) / baseline * 100`, so positive percentages are better.
- In bar charts, include every compared implementation, including the baseline. Start the scale at zero and make each bar proportional to its actual value within that workload row, with the worst result at 100% length and better results shorter. Label every bar with its absolute measurement and its consumption change relative to the baseline, where a negative percentage means less time or allocation and is therefore better.
- Mark the numerically best value in each comparable row. Preserve the JMH uncertainty next to each score so the reader can see overlaps without adding narrative findings.
- Treat `gc.count` and `gc.time` as supporting diagnostics, not primary heap-efficiency measures.

Native-memory summaries contain allocation samples, not live or peak native memory. Raw bytes and sample counts vary with the number of operations completed and must not be ranked directly. The helper estimates native allocated bytes per operation as:

`summed sampled allocation bytes * matching JMH time per operation / profiled measurement time`

The repository command profiles the benchmark method ending in `Throughput` at every `chunkSize`, with three 5-second measurement iterations, so the helper defaults to 15 seconds. Normalize each native profile with the matching JMH time for the same chunk size. If the command or run duration changed, pass `--native-seconds` with the actual total measured seconds. Only compare estimates produced with equivalent profiler settings. Call this metric “estimated native allocation per operation,” never “native memory usage” or “peak memory.”

Use flamegraphs as qualitative evidence for hot paths and explain meaningful differences when visually inspected. Do not derive timing percentages or memory quantities from flamegraph widths. Link each flamegraph from the report so a reader can inspect it.

## Report requirements

Write only these files inside the selected benchmark directory:

- `comparison-jdk25-charts.md`: a title, compact implementation, input-file, and benchmark-host metadata, a one-sentence explanation of the percentage convention, and the three chart embeds;
- `comparison-jdk25-{performance,heap,native}.svg`: chart assets embedded by the chart-enhanced report.

Do not add tables, artifact lists, findings, conclusions, calculation sections, or interpretation sections to the Markdown report. The absolute measurements and percentage deltas belong directly on the SVG bars. Do not imply causation from a flamegraph or claim resident-memory improvements from allocation profiling.
