package org.zygiert;

import com.github.luben.zstd.Zstd;
import org.openjdk.jmh.annotations.*;

import java.util.concurrent.TimeUnit;

@BenchmarkMode(Mode.AverageTime)
@OutputTimeUnit(TimeUnit.MICROSECONDS)
// Fixed, pre-committed heap: -Xms == -Xmx keeps the JVM from resizing mid-run, and
// AlwaysPreTouch faults every page in at startup instead of during the measured iterations.
@Fork(value = 3, jvmArgsAppend = {"-Xms2g", "-Xmx2g", "-XX:+AlwaysPreTouch", "-XX:+UseG1GC"})
@Warmup(iterations = 3, time = 3, timeUnit = TimeUnit.SECONDS)
@Measurement(iterations = 5, time = 5, timeUnit = TimeUnit.SECONDS)
@State(Scope.Benchmark)
public class ZstdErrorNameBenchmark {
    // zstd functions return errors as negated codes.
    private final long errorCode = -Zstd.errDstSizeTooSmall();

    @Benchmark
    public String getErrorNameThroughput() {
        return Zstd.getErrorName(errorCode);
    }
}
