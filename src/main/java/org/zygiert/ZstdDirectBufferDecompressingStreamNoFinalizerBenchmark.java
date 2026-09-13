package org.zygiert;

import com.github.luben.zstd.Zstd;
import com.github.luben.zstd.ZstdDirectBufferDecompressingStream;
import org.openjdk.jmh.annotations.Benchmark;
import org.openjdk.jmh.annotations.BenchmarkMode;
import org.openjdk.jmh.annotations.Fork;
import org.openjdk.jmh.annotations.Measurement;
import org.openjdk.jmh.annotations.Mode;
import org.openjdk.jmh.annotations.OutputTimeUnit;
import org.openjdk.jmh.annotations.Param;
import org.openjdk.jmh.annotations.Scope;
import org.openjdk.jmh.annotations.Setup;
import org.openjdk.jmh.annotations.State;
import org.openjdk.jmh.annotations.Warmup;

import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.util.concurrent.TimeUnit;

@BenchmarkMode(Mode.AverageTime)
@OutputTimeUnit(TimeUnit.MICROSECONDS)
// Fixed, pre-committed heap: -Xms == -Xmx keeps the JVM from resizing mid-run, and
// AlwaysPreTouch faults every page in at startup instead of during the measured iterations.
@Fork(value = 3, jvmArgsAppend = {"-Xms2g", "-Xmx2g", "-XX:+AlwaysPreTouch", "-XX:+UseG1GC"})
@Warmup(iterations = 3, time = 3, timeUnit = TimeUnit.SECONDS)
@Measurement(iterations = 5, time = 5, timeUnit = TimeUnit.SECONDS)
public class ZstdDirectBufferDecompressingStreamNoFinalizerBenchmark {

    private static final int LEVEL = 1;

    // This benchmark is intentionally run with one worker thread. The state owns a mutable,
    // reusable target buffer and must not be shared by parallel benchmark invocations.
    @State(Scope.Benchmark)
    public static class ThroughputState {
        @Param({"1", "8", "64", "512", "4096", "16384", "65536"})
        private int chunkSize;

        private ByteBuffer compressedData;
        private ByteBuffer target;

        @Setup
        public void setup() throws IOException {
            try (InputStream is = getClass().getResourceAsStream("/dataset-formatted.xml")) {
                byte[] compressed = Zstd.compress(is.readAllBytes(), LEVEL);
                this.compressedData = ByteBuffer.allocateDirect(compressed.length);
                this.compressedData.put(compressed).flip();
            }
            this.target = ByteBuffer.allocateDirect(chunkSize);
        }
    }

    @Benchmark
    public int decompressionThroughput(ThroughputState state) throws IOException {
        int totalBytesRead = 0;
        try (ZstdDirectBufferDecompressingStream in = new ZstdDirectBufferDecompressingStream(state.compressedData.duplicate())) {
            while (in.hasRemaining()) {
                state.target.clear();
                totalBytesRead += in.read(state.target);
            }
        }
        return totalBytesRead;
    }

    @Benchmark
    public void createAndClose() throws IOException {
        try (ZstdDirectBufferDecompressingStream in =
                     new ZstdDirectBufferDecompressingStream(ByteBuffer.allocateDirect(0))) {
            // no reads — isolates construction/teardown cost only
        }
    }
}
