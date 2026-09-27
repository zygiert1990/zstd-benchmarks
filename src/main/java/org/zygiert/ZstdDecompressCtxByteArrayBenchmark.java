package org.zygiert;

import com.github.luben.zstd.Zstd;
import com.github.luben.zstd.ZstdDecompressCtx;
import org.openjdk.jmh.annotations.Benchmark;
import org.openjdk.jmh.annotations.BenchmarkMode;
import org.openjdk.jmh.annotations.Fork;
import org.openjdk.jmh.annotations.Measurement;
import org.openjdk.jmh.annotations.Mode;
import org.openjdk.jmh.annotations.OutputTimeUnit;
import org.openjdk.jmh.annotations.Scope;
import org.openjdk.jmh.annotations.Setup;
import org.openjdk.jmh.annotations.State;
import org.openjdk.jmh.annotations.TearDown;
import org.openjdk.jmh.annotations.Warmup;

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
public class ZstdDecompressCtxByteArrayBenchmark {
    private ZstdDecompressCtx context;
    private byte[] compressed;
    private byte[] target;

    @Setup
    public void setup() throws IOException {
        byte[] data;
        try (InputStream input = getClass().getResourceAsStream("/dataset-formatted.xml")) {
            if (input == null) {
                throw new IOException("dataset-formatted.xml not found");
            }
            data = input.readAllBytes();
        }
        compressed = Zstd.compress(data, 1);
        target = new byte[data.length];
        context = new ZstdDecompressCtx();
    }

    @TearDown
    public void tearDown() {
        context.close();
    }

    @Benchmark
    public int decompressionThroughput() {
        return context.decompressByteArray(target, 0, target.length, compressed, 0, compressed.length);
    }
}
