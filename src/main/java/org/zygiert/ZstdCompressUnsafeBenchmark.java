package org.zygiert;

import com.github.luben.zstd.Zstd;
import org.openjdk.jmh.annotations.*;

import java.io.IOException;
import java.io.InputStream;
import java.lang.reflect.Field;
import java.nio.Buffer;
import java.nio.ByteBuffer;
import java.util.concurrent.TimeUnit;

@BenchmarkMode(Mode.AverageTime)
@OutputTimeUnit(TimeUnit.MICROSECONDS)
// Fixed, pre-committed heap: -Xms == -Xmx keeps the JVM from resizing mid-run, and
// AlwaysPreTouch faults every page in at startup instead of during the measured iterations.
// --add-opens lets setup read direct buffer addresses (see address()) on JDK 16+.
@Fork(value = 3, jvmArgsAppend = {"-Xms2g", "-Xmx2g", "-XX:+AlwaysPreTouch", "-XX:+UseG1GC",
        "--add-opens", "java.base/java.nio=ALL-UNNAMED"})
@Warmup(iterations = 3, time = 3, timeUnit = TimeUnit.SECONDS)
@Measurement(iterations = 5, time = 5, timeUnit = TimeUnit.SECONDS)
@State(Scope.Benchmark)
public class ZstdCompressUnsafeBenchmark {
    private static final int LEVEL = 1;

    // The state owns the direct buffers whose raw addresses are passed to zstd, so the buffers stay
    // strongly reachable (and their memory valid) for the whole trial.
    private ByteBuffer source;
    private ByteBuffer target;
    private long sourceAddress;
    private long sourceSize;
    private long targetAddress;
    private long targetCapacity;

    @Setup(Level.Trial)
    public void setup() throws IOException {
        byte[] data;
        try (InputStream input = getClass().getResourceAsStream("/dataset-formatted.xml")) {
            if (input == null) {
                throw new IOException("dataset-formatted.xml not found");
            }
            data = input.readAllBytes();
        }
        source = ByteBuffer.allocateDirect(data.length);
        source.put(data).flip();
        target = ByteBuffer.allocateDirect(Math.toIntExact(Zstd.compressBound(source.capacity())));
        sourceAddress = address(source);
        sourceSize = source.capacity();
        targetAddress = address(target);
        targetCapacity = target.capacity();
    }

    // ByteBuffer has no public address getter that works on both Java 11 and 22+, so read the
    // internal Buffer.address field, once per trial.
    private static long address(ByteBuffer buffer) {
        try {
            Field address = Buffer.class.getDeclaredField("address");
            address.setAccessible(true);
            return address.getLong(buffer);
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException("Cannot read direct buffer address", e);
        }
    }

    @Benchmark
    public long compressionThroughput() {
        return Zstd.compressUnsafe(targetAddress, targetCapacity, sourceAddress, sourceSize, LEVEL, false);
    }
}
