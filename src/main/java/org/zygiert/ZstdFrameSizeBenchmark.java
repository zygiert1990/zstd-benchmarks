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
public class ZstdFrameSizeBenchmark {
    private static final int LEVEL = 1;
    private static final int OFFSET = 16;
    private byte[] frame;
    private byte[] magiclessFrame;
    private ByteBuffer directFrame;
    private ByteBuffer paddedDirectFrame;

    @Setup(Level.Trial)
    public void setup() throws IOException {
        byte[] data;
        try (InputStream input = getClass().getResourceAsStream("/dataset-formatted.xml")) {
            if (input == null) {
                throw new IOException("dataset-formatted.xml not found");
            }
            data = input.readAllBytes();
        }
        frame = Zstd.compress(data, LEVEL);
        try (ZstdCompressCtx context = new ZstdCompressCtx()) {
            magiclessFrame = context.setLevel(LEVEL).setMagicless(true).compress(data);
        }
        // Whole buffer is the frame: position 0, limit = frame size.
        directFrame = ByteBuffer.allocateDirect(frame.length);
        directFrame.put(frame).flip();
        // Frame surrounded by padding, addressed with an explicit offset and size.
        paddedDirectFrame = ByteBuffer.allocateDirect(OFFSET + frame.length + OFFSET);
        paddedDirectFrame.position(OFFSET);
        paddedDirectFrame.put(frame).clear();
    }

    @Benchmark
    public long getFrameContentSizeHeapThroughput() {
        return Zstd.getFrameContentSize(frame, 0, frame.length, false);
    }

    @Benchmark
    public long getFrameContentSizeHeapMagiclessThroughput() {
        return Zstd.getFrameContentSize(magiclessFrame, 0, magiclessFrame.length, true);
    }

    @Benchmark
    public long getFrameContentSizeDirectThroughput() {
        return Zstd.getFrameContentSize(directFrame);
    }

    @Benchmark
    public long findDirectByteBufferFrameCompressedSizeThroughput() {
        return Zstd.findDirectByteBufferFrameCompressedSize(paddedDirectFrame, OFFSET, frame.length);
    }
}
