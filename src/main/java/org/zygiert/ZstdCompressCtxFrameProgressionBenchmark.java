package org.zygiert;

import com.github.luben.zstd.EndDirective;
import com.github.luben.zstd.Zstd;
import com.github.luben.zstd.ZstdCompressCtx;
import com.github.luben.zstd.ZstdFrameProgression;
import org.openjdk.jmh.annotations.*;

import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.util.concurrent.TimeUnit;

/**
 * Measures one progression snapshot, including allocation of ZstdFrameProgression.
 * Setup compresses and flushes 64 KiB but leaves the frame open.
 * Compression and flushing are excluded from the measured getter call.
 */
@BenchmarkMode(Mode.AverageTime)
@OutputTimeUnit(TimeUnit.MICROSECONDS)
// Fixed, pre-committed heap: -Xms == -Xmx keeps the JVM from resizing mid-run, and
// AlwaysPreTouch faults every page in at startup instead of during the measured iterations.
@Fork(value = 3, jvmArgsAppend = {"-Xms2g", "-Xmx2g", "-XX:+AlwaysPreTouch", "-XX:+UseG1GC"})
@Warmup(iterations = 3, time = 3, timeUnit = TimeUnit.SECONDS)
@Measurement(iterations = 5, time = 5, timeUnit = TimeUnit.SECONDS)
@State(Scope.Benchmark)
public class ZstdCompressCtxFrameProgressionBenchmark {

    private static final int PROGRESSED_BYTES = 65536;

    private ZstdCompressCtx context;

    @Setup
    public void setup() throws IOException {
        byte[] data;
        try (InputStream input = getClass().getResourceAsStream("/dataset-formatted.xml")) {
            if (input == null) {
                throw new IOException("dataset-formatted.xml not found");
            }
            data = input.readAllBytes();
        }
        if (data.length < PROGRESSED_BYTES) {
            throw new IllegalArgumentException("Dataset must contain at least 64 KiB");
        }

        ByteBuffer source = ByteBuffer.allocateDirect(PROGRESSED_BYTES);
        source.put(data, 0, PROGRESSED_BYTES).flip();
        ByteBuffer target = ByteBuffer.allocateDirect(Math.toIntExact(Zstd.compressBound(PROGRESSED_BYTES)));
        context = new ZstdCompressCtx().setLevel(1);

        while (true) {
            int sourcePosition = source.position();
            int targetPosition = target.position();
            if (context.compressByteBufferStream(target, source, EndDirective.FLUSH)) {
                break;
            }
            if (source.position() == sourcePosition && target.position() == targetPosition) {
                throw new IllegalStateException("Compression made no progress; output remaining=" + target.remaining());
            }
        }

        ZstdFrameProgression progression = context.getFrameProgression();
        if (source.hasRemaining()
                || progression.getIngested() != PROGRESSED_BYTES
                || progression.getConsumed() != PROGRESSED_BYTES
                || progression.getProduced() <= 0) {
            throw new IllegalStateException("Expected a flushed, unfinished frame");
        }
    }

    @TearDown
    public void tearDown() {
        context.close();
    }

    @Benchmark
    public ZstdFrameProgression progressionThroughput() {
        return context.getFrameProgression();
    }
}
