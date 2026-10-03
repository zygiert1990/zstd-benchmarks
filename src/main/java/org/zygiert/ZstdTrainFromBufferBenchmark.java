package org.zygiert;

import com.github.luben.zstd.Zstd;
import org.openjdk.jmh.annotations.*;

import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.util.Arrays;
import java.util.concurrent.TimeUnit;

@BenchmarkMode(Mode.AverageTime)
@OutputTimeUnit(TimeUnit.MICROSECONDS)
// Fixed, pre-committed heap: -Xms == -Xmx keeps the JVM from resizing mid-run, and
// AlwaysPreTouch faults every page in at startup instead of during the measured iterations.
@Fork(value = 3, jvmArgsAppend = {"-Xms2g", "-Xmx2g", "-XX:+AlwaysPreTouch", "-XX:+UseG1GC"})
@Warmup(iterations = 3, time = 3, timeUnit = TimeUnit.SECONDS)
@Measurement(iterations = 5, time = 5, timeUnit = TimeUnit.SECONDS)
@State(Scope.Benchmark)
public class ZstdTrainFromBufferBenchmark {
    private static final int LEVEL = 1;
    private static final int SAMPLE_SIZE = 1024;
    private static final int DICTIONARY_CAPACITY = 8192;
    private byte[][] samples;
    private byte[] dictionary;
    private ByteBuffer packedSamples;
    private int[] sampleSizes;
    private ByteBuffer directDictionary;

    @Setup(Level.Trial)
    public void setup() throws IOException {
        byte[] source;
        try (InputStream input = getClass().getResourceAsStream("/dataset-formatted.xml")) {
            if (input == null) {
                throw new IOException("dataset-formatted.xml not found");
            }
            source = input.readAllBytes();
        }
        // Deterministic 1 KiB samples covering the whole dataset (the last one may be shorter).
        int sampleCount = (source.length + SAMPLE_SIZE - 1) / SAMPLE_SIZE;
        samples = new byte[sampleCount][];
        sampleSizes = new int[sampleCount];
        // trainFromBufferDirect reads from the buffer base up to its capacity, ignoring position/limit,
        // so the buffer is sized to exactly the packed total.
        packedSamples = ByteBuffer.allocateDirect(source.length);
        for (int i = 0; i < sampleCount; i++) {
            int offset = i * SAMPLE_SIZE;
            samples[i] = Arrays.copyOfRange(source, offset, Math.min(offset + SAMPLE_SIZE, source.length));
            sampleSizes[i] = samples[i].length;
            packedSamples.put(samples[i]);
        }
        packedSamples.clear();
        dictionary = new byte[DICTIONARY_CAPACITY];
        directDictionary = ByteBuffer.allocateDirect(DICTIONARY_CAPACITY);
    }

    @Benchmark
    public long trainFromBufferThroughput() {
        return Zstd.trainFromBuffer(samples, dictionary, false, LEVEL);
    }

    @Benchmark
    public long trainFromBufferDirectThroughput() {
        return Zstd.trainFromBufferDirect(packedSamples, sampleSizes, directDictionary, false, LEVEL);
    }
}
