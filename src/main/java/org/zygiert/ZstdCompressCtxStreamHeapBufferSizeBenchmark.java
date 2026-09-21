package org.zygiert;

import com.github.luben.zstd.EndDirective;
import com.github.luben.zstd.ZstdCompressCtx;
import org.openjdk.jmh.annotations.*;

import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.util.concurrent.TimeUnit;

/**
 * Varies both backing-array capacities while keeping the input data and the 4 KiB
 * input chunk size fixed. Padding beyond the dataset is never compressed.
 */
@BenchmarkMode(Mode.AverageTime)
@OutputTimeUnit(TimeUnit.MICROSECONDS)
// Fixed, pre-committed heap: -Xms == -Xmx keeps the JVM from resizing mid-run, and
// AlwaysPreTouch faults every page in at startup instead of during the measured iterations.
@Fork(value = 3, jvmArgsAppend = {"-Xms2g", "-Xmx2g", "-XX:+AlwaysPreTouch", "-XX:+UseG1GC"})
@Warmup(iterations = 3, time = 3, timeUnit = TimeUnit.SECONDS)
@Measurement(iterations = 5, time = 5, timeUnit = TimeUnit.SECONDS)
@State(Scope.Benchmark)
public class ZstdCompressCtxStreamHeapBufferSizeBenchmark {

    private static final int CHUNK_SIZE = 4096;

    @Param({"262144", "524288", "1048576", "2097152"})
    private int bufferSize;

    private int dataSize;
    private ZstdCompressCtx context;
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
        if (bufferSize < data.length) {
            throw new IllegalArgumentException("bufferSize is too small for the dataset");
        }

        dataSize = data.length;
        source = ByteBuffer.allocate(bufferSize);
        source.put(data).flip();
        target = ByteBuffer.allocate(bufferSize);
        context = new ZstdCompressCtx().setLevel(1);
    }

    @TearDown
    public void tearDown() {
        context.close();
    }

    @Benchmark
    public int compressionThroughput() {
        source.clear().limit(dataSize);
        target.clear();

        while (source.hasRemaining()) {
            int fullLimit = source.limit();
            source.limit(source.position() + Math.min(CHUNK_SIZE, source.remaining()));
            while (source.hasRemaining()) {
                int sourcePosition = source.position();
                int targetPosition = target.position();
                context.compressByteBufferStream(target, source, EndDirective.CONTINUE);
                ensureProgress(sourcePosition, targetPosition);
            }
            source.limit(fullLimit);
        }

        while (true) {
            int sourcePosition = source.position();
            int targetPosition = target.position();
            if (context.compressByteBufferStream(target, source, EndDirective.END)) {
                return target.position();
            }
            ensureProgress(sourcePosition, targetPosition);
        }
    }

    private void ensureProgress(int sourcePosition, int targetPosition) {
        if (source.position() == sourcePosition && target.position() == targetPosition) {
            throw new IllegalStateException("Compression made no progress; output remaining=" + target.remaining());
        }
    }
}
