## Quick start
Needs Java 11 or above due to `nullOutputStream` usage.

Commands for java 11 assume that there is a java binary under: `~/.sdkman/candidates/java/11.0.32-amzn/bin/java`

To create jar: `mvn clean package`

To run benchmarks (disable sleep on ubuntu 22): `gnome-session-inhibit --inhibit idle:suspend --reason "Running JMH" java -jar target/benchmarks.jar ZstdOutputStreamNoFinalizerBenchmark -prof gc`

To run benchmarks (disable sleep on ubuntu 22) (java 11): `gnome-session-inhibit --inhibit idle:suspend --reason "Running JMH" java -jar target/benchmarks.jar ZstdOutputStreamNoFinalizerBenchmark -prof gc -jvm ~/.sdkman/candidates/java/11.0.32-amzn/bin/java`

To attach async-profiler native mem allocation: `java -jar target/benchmarks.jar ZstdOutputStreamNoFinalizerBenchmark.compressionThroughput -p chunkSize=64 -prof "async:libPath=$HOME/tools/async-profiler-4.5-linux-x64/lib/libasyncProfiler.so;event=nativemem;output=text" -f 1 -wi 3 -i 3`

To attach async-profiler native mem allocation (java 11): `java -jar target/benchmarks.jar ZstdOutputStreamNoFinalizerBenchmark.compressionThroughput -p chunkSize=64 -prof "async:libPath=$HOME/tools/async-profiler-4.5-linux-x64/lib/libasyncProfiler.so;event=nativemem;output=text" -f 1 -wi 3 -i 3 -jvm ~/.sdkman/candidates/java/11.0.32-amzn/bin/java`

To produce a CPU flamegraph into `target/`: `gnome-session-inhibit --inhibit idle:suspend --reason "Running JMH" java -jar target/benchmarks.jar ZstdOutputStreamNoFinalizerBenchmark.compressionThroughput -p chunkSize=64 -prof "async:libPath=$HOME/tools/async-profiler-4.5-linux-x64/lib/libasyncProfiler.so;event=cpu;output=flamegraph;dir=target/async-profiler"`

To produce a CPU flamegraph into `target/` (java 11): `gnome-session-inhibit --inhibit idle:suspend --reason "Running JMH" java -jar target/benchmarks.jar ZstdOutputStreamNoFinalizerBenchmark.compressionThroughput -p chunkSize=64 -prof "async:libPath=$HOME/tools/async-profiler-4.5-linux-x64/lib/libasyncProfiler.so;event=cpu;output=flamegraph;dir=target/async-profiler" -jvm ~/.sdkman/candidates/java/11.0.32-amzn/bin/java`

## Automated benchmark runs

Run the complete benchmark and profiler matrix with a benchmark class followed by zero or more
`zstd-jni` version/result-name pairs:

```bash
./run-benchmarks.sh ZstdInputStreamNoFinalizerBenchmark \
  1.5.7-16-V1 ffm \
  1.5.7-16-V2-GCC ffm-gcc
```

The script always runs `1.5.7-16-LOCAL` as `orig`. It runs `orig` on Java 25 and Java 11,
runs additional versions on Java 25, recreates `docs/<BenchmarkName>/`, and restores the original
`pom.xml` when it exits. Native-memory summaries and CPU flamegraphs are produced separately for
every configured `chunkSize`.

The defaults target the benchmark environment recorded in [`docs/readme.md`](docs/readme.md):

- Ubuntu 22.04.5 LTS on AMD64
- Intel Core i5-8500, 6 physical / 6 logical cores, 16 GB RAM
- Temurin 25.0.2 at `~/.sdkman/candidates/java/25.0.2-tem/bin/java`
- Corretto 11.0.32 at `~/.sdkman/candidates/java/11.0.32-amzn/bin/java`
- async-profiler 4.5 at `~/tools/async-profiler-4.5-linux-x64/lib/libasyncProfiler.so`

Set `DEFAULT_JAVA`, `JAVA_11`, or `ASYNC_PROFILER_LIB` to adjust the executable and profiler paths
for another local setup.
