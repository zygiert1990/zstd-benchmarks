package org.zygiert;

import com.github.luben.zstd.Zstd;
import com.github.luben.zstd.ZstdInputStream;
import org.openjdk.jmh.annotations.*;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.concurrent.TimeUnit;

@BenchmarkMode(Mode.AverageTime)
@OutputTimeUnit(TimeUnit.MICROSECONDS)
@Fork(3)
@Warmup(iterations = 3, time = 3, timeUnit = TimeUnit.SECONDS)
@Measurement(iterations = 5, time = 5, timeUnit = TimeUnit.SECONDS)
public class ZstdInputStreamNoFinalizerBenchmark {

    private static final int LEVEL = 1;

    @State(Scope.Benchmark)
    public static class ThroughputState {
        @Param({"1", "8", "64", "512", "4096", "16384", "65536"})
        private int chunkSize;

        private byte[] compressedData;

        @Setup()
        public void setup() throws IOException {
            try (InputStream is = getClass().getResourceAsStream("/dataset-formatted.xml")) {
                this.compressedData = Zstd.compress(is.readAllBytes(), LEVEL);
            }
        }
    }

    @Benchmark
    public int decompressionThroughput(ThroughputState state) throws IOException {
        byte[] buffer = new byte[state.chunkSize];
        int totalBytesRead = 0;
        try (ZstdInputStream in = new ZstdInputStream(new ByteArrayInputStream(state.compressedData))) {
            int bytesRead;
            while ((bytesRead = in.read(buffer)) != -1) {
                totalBytesRead += bytesRead;
            }
        }
        return totalBytesRead;
    }

    @Benchmark
    public void createAndClose() throws IOException {
        try (ZstdInputStream in = new ZstdInputStream(InputStream.nullInputStream())) {
            // no reads — isolates construction/teardown cost only
        }
    }
}
