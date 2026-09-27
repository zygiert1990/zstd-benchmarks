package org.zygiert;

import com.github.luben.zstd.Zstd;
import com.github.luben.zstd.ZstdDecompressCtx;
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
import org.openjdk.jmh.annotations.TearDown;
import org.openjdk.jmh.annotations.Warmup;

import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.util.concurrent.TimeUnit;

/**
 * Measures reusable-context streaming with bounded output buffers. The source remains fully
 * available, while chunkSize controls how much decompressed output each call can produce.
 */
@BenchmarkMode(Mode.AverageTime)
@OutputTimeUnit(TimeUnit.MICROSECONDS)
// Fixed, pre-committed heap: -Xms == -Xmx keeps the JVM from resizing mid-run, and
// AlwaysPreTouch faults every page in at startup instead of during the measured iterations.
@Fork(value = 3, jvmArgsAppend = {"-Xms2g", "-Xmx2g", "-XX:+AlwaysPreTouch", "-XX:+UseG1GC"})
@Warmup(iterations = 3, time = 3, timeUnit = TimeUnit.SECONDS)
@Measurement(iterations = 5, time = 5, timeUnit = TimeUnit.SECONDS)
@State(Scope.Benchmark)
public class ZstdDecompressCtxStreamDirectBenchmark {

    @Param({"1", "8", "64", "512", "4096", "16384", "65536"})
    private int chunkSize;

    private int compressedSize;
    private int dataSize;
    private ZstdDecompressCtx context;
    private ByteBuffer source;
    private ByteBuffer target;

    @Setup
    public void setup() throws IOException {
        byte[] data;
        try (InputStream input = getClass().getResourceAsStream("/dataset-formatted.xml")) {
            if (input == null) {
                throw new IOException("dataset-formatted.xml not found");
            }
            data = input.readAllBytes();
        }

        byte[] compressed = Zstd.compress(data, 1);
        compressedSize = compressed.length;
        dataSize = data.length;
        source = ByteBuffer.allocateDirect(compressedSize);
        source.put(compressed).flip();
        target = ByteBuffer.allocateDirect(dataSize);
        context = new ZstdDecompressCtx();
    }

    @TearDown
    public void tearDown() {
        context.close();
    }

    @Benchmark
    public int decompressionThroughput() {
        source.clear().limit(compressedSize);
        target.clear().limit(dataSize);

        boolean finished = false;
        while (!finished) {
            if (!target.hasRemaining()) {
                throw new IllegalStateException("Decompression did not finish after filling the target");
            }

            int fullLimit = target.limit();
            target.limit(target.position() + Math.min(chunkSize, target.remaining()));
            int sourcePosition = source.position();
            int targetPosition = target.position();
            finished = context.decompressDirectByteBufferStream(target, source);
            ensureProgress(sourcePosition, targetPosition);
            target.limit(fullLimit);
        }

        if (source.hasRemaining()) {
            throw new IllegalStateException("Decompression finished before consuming the source");
        }
        return target.position();
    }

    private void ensureProgress(int sourcePosition, int targetPosition) {
        if (source.position() == sourcePosition && target.position() == targetPosition) {
            throw new IllegalStateException("Decompression made no progress; output remaining=" + target.remaining());
        }
    }
}
