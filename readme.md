## Quick start
Needs Java 11 or above due to `nullOutputStream` usage.

To create jar: `mvn clean package`

To run benchmarks (disable sleep on ubuntu 22): `gnome-session-inhibit --inhibit idle:suspend --reason "Running JMH" java -jar target/benchmarks.jar ZstdOutputStreamNoFinalizerBenchmark -prof gc`

To run benchmarks (disable sleep on ubuntu 22) (java 11): `gnome-session-inhibit --inhibit idle:suspend --reason "Running JMH" java -jar target/benchmarks.jar ZstdOutputStreamNoFinalizerBenchmark -prof gc -jvm ~/.sdkman/candidates/java/11.0.32-amzn/bin/java`

To attach async-profiler native mem allocation: `java -jar target/benchmarks.jar ZstdOutputStreamNoFinalizerBenchmark.compressionThroughput -p chunkSize=64 -prof "async:libPath=$HOME/tools/async-profiler-4.5-linux-x64/lib/libasyncProfiler.so;event=nativemem;output=text" -f 1 -wi 3 -i 3`

To attach async-profiler native mem allocation (java 11): `java -jar target/benchmarks.jar ZstdOutputStreamNoFinalizerBenchmark.compressionThroughput -p chunkSize=64 -prof "async:libPath=$HOME/tools/async-profiler-4.5-linux-x64/lib/libasyncProfiler.so;event=nativemem;output=text" -f 1 -wi 3 -i 3 -jvm ~/.sdkman/candidates/java/11.0.32-amzn/bin/java`

To produce a CPU flamegraph into `target/`: `gnome-session-inhibit --inhibit idle:suspend --reason "Running JMH" java -jar target/benchmarks.jar ZstdOutputStreamNoFinalizerBenchmark.compressionThroughput -p chunkSize=64 -prof "async:libPath=$HOME/tools/async-profiler-4.5-linux-x64/lib/libasyncProfiler.so;event=cpu;output=flamegraph;dir=target/async-profiler"`

To produce a CPU flamegraph into `target/` (java 11): `gnome-session-inhibit --inhibit idle:suspend --reason "Running JMH" java -jar target/benchmarks.jar ZstdOutputStreamNoFinalizerBenchmark.compressionThroughput -p chunkSize=64 -prof "async:libPath=$HOME/tools/async-profiler-4.5-linux-x64/lib/libasyncProfiler.so;event=cpu;output=flamegraph;dir=target/async-profiler" -jvm ~/.sdkman/candidates/java/11.0.32-amzn/bin/java`