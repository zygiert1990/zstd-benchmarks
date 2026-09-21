package org.zygiert;

import com.github.luben.zstd.Zstd;
import com.github.luben.zstd.ZstdCompressCtx;
import org.openjdk.jmh.annotations.*;

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
@State(Scope.Benchmark)
public class ZstdCompressCtxDirectBufferBenchmark {
    private ZstdCompressCtx context;
    private ByteBuffer source;
    private ByteBuffer target;

    @Setup
    public void setup() throws IOException {
        try (InputStream is = getClass().getResourceAsStream("/dataset-formatted.xml")) {
            if (is == null) {
                throw new IOException("dataset-formatted.xml not found");
            }
            byte[] input = is.readAllBytes();
            source = ByteBuffer.allocateDirect(input.length);
            source.put(input).flip();
            target = ByteBuffer.allocateDirect(Math.toIntExact(Zstd.compressBound(input.length)));
        }
        context = new ZstdCompressCtx().setLevel(1);
    }

    @TearDown
    public void tearDown() {
        context.close();
    }

    @Benchmark
    public int compressionThroughput() {
        return context.compressDirectByteBuffer(target, 0, target.capacity(), source, 0, source.capacity());
    }
}
