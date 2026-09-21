package org.zygiert;

import com.github.luben.zstd.Zstd;
import com.github.luben.zstd.ZstdCompressCtx;
import org.openjdk.jmh.annotations.*;

import java.io.IOException;
import java.io.InputStream;
import java.util.concurrent.TimeUnit;

@BenchmarkMode(Mode.AverageTime)
@OutputTimeUnit(TimeUnit.MICROSECONDS)
// Fixed, pre-committed heap: -Xms == -Xmx keeps the JVM from resizing mid-run, and
// AlwaysPreTouch faults every page in at startup instead of during the measured iterations.
@Fork(value = 3, jvmArgsAppend = {"-Xms2g", "-Xmx2g", "-XX:+AlwaysPreTouch", "-XX:+UseG1GC"})
@Warmup(iterations = 3, time = 3, timeUnit = TimeUnit.SECONDS)
@Measurement(iterations = 5, time = 5, timeUnit = TimeUnit.SECONDS)
@State(Scope.Benchmark)
public class ZstdCompressCtxByteArrayBenchmark {
    private ZstdCompressCtx context;
    private byte[] source;
    private byte[] target;

    @Setup
    public void setup() throws IOException {
        try (InputStream input = getClass().getResourceAsStream("/dataset-formatted.xml")) {
            if (input == null) {
                throw new IOException("dataset-formatted.xml not found");
            }
            source = input.readAllBytes();
        }
        target = new byte[Math.toIntExact(Zstd.compressBound(source.length))];
        context = new ZstdCompressCtx().setLevel(1);
    }

    @TearDown
    public void tearDown() {
        context.close();
    }

    @Benchmark
    public int compressionThroughput() {
        return context.compressByteArray(target, 0, target.length, source, 0, source.length);
    }
}
