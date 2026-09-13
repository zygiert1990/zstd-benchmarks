# Benchmark scripts

## Generate comparison charts

Run the chart generator with one benchmark result directory:

```bash
python3 scripts/compare_benchmarks.py docs/ZstdOutputStreamNoFinalizerBenchmark
```

The directory must contain `results.txt`, `summary-nativemem.txt`,
`results-nativemem.json`, and `flame-cpu-forward.html` artifacts produced by
`run-benchmarks.sh`. Its `readme.md` must identify the tested implementations, and
`docs/readme.md` must contain the benchmark-host metadata.

The command writes `comparison-jdk25-charts.md` and the performance, heap, and native-allocation
SVG charts into the selected benchmark directory. The input directory is resolved independently
of the script location, so an absolute directory path also works when invoking the script from
outside the repository.

Use `python3 scripts/compare_benchmarks.py --help` to list command-line options.
