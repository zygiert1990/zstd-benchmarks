package org.zygiert;

import com.github.luben.zstd.ZstdDictCompress;
import com.github.luben.zstd.ZstdDictTrainer;
import org.openjdk.jmh.annotations.*;

import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.util.Arrays;
import java.util.concurrent.TimeUnit;

@BenchmarkMode(Mode.AverageTime)
@OutputTimeUnit(TimeUnit.MICROSECONDS)
@Fork(value = 3, jvmArgsAppend = {"-Xms2g", "-Xmx2g", "-XX:+AlwaysPreTouch", "-XX:+UseG1GC"})
@Warmup(iterations = 3, time = 3, timeUnit = TimeUnit.SECONDS)
@Measurement(iterations = 5, time = 5, timeUnit = TimeUnit.SECONDS)
@State(Scope.Thread)
public class ZstdDictCompressLifecycleBenchmark {
    private static final int OFFSET = 16;
    private byte[] heapDictionary;
    private ByteBuffer directDictionary;
    private int dictionarySize;

    @Setup(Level.Trial)
    public void setup() throws IOException {
        byte[] source;
        try (InputStream input = getClass().getResourceAsStream("/dataset-formatted.xml")) {
            if (input == null) {
                throw new IOException("dataset-formatted.xml not found");
            }
            source = input.readAllBytes();
        }
        // Train once, outside timing, from deterministic 1 KiB samples of the shared dataset.
        ZstdDictTrainer trainer = new ZstdDictTrainer(source.length, 8192);
        for (int offset = 0; offset < source.length; offset += 1024) {
            if (!trainer.addSample(Arrays.copyOfRange(source, offset, Math.min(offset + 1024, source.length)))) {
                throw new IllegalStateException("Dictionary training sample buffer is full");
            }
        }
        byte[] dictionary = trainer.trainSamples();
        dictionarySize = dictionary.length;
        // Exercise the offset/range handling in both implementations, excluding padding.
        heapDictionary = new byte[OFFSET + dictionarySize + OFFSET];
        System.arraycopy(dictionary, 0, heapDictionary, OFFSET, dictionarySize);
        directDictionary = ByteBuffer.allocateDirect(heapDictionary.length);
        directDictionary.position(OFFSET);
        directDictionary.put(dictionary);
        directDictionary.limit(OFFSET + dictionarySize).position(OFFSET);
        // Keep this buffer alive and unmodified for every by-reference dictionary lifetime.
    }

    @Benchmark
    public void createHeapAndCloseThroughput() {
        try (ZstdDictCompress ignored = new ZstdDictCompress(heapDictionary, OFFSET, dictionarySize, 1)) {
            // Measure native dictionary creation and release together.
        }
    }

    @Benchmark
    public void createDirectCopyAndCloseThroughput() {
        try (ZstdDictCompress ignored = new ZstdDictCompress(directDictionary, 1)) {
            // Measure native dictionary creation and release together.
        }
    }

    @Benchmark
    public void createDirectReferenceAndCloseThroughput() {
        try (ZstdDictCompress ignored = new ZstdDictCompress(directDictionary, 1, true)) {
            // Measure native dictionary creation and release together.
        }
    }
}
