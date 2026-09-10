package org.zygiert;

import com.github.luben.zstd.ZstdOutputStream;
import org.openjdk.jmh.annotations.*;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.concurrent.TimeUnit;

@BenchmarkMode(Mode.AverageTime)
@OutputTimeUnit(TimeUnit.MICROSECONDS)
@Fork(3)
@Warmup(iterations = 3, time = 3, timeUnit = TimeUnit.SECONDS)
@Measurement(iterations = 5, time = 5, timeUnit = TimeUnit.SECONDS)
public class ZstdOutputStreamNoFinalizerBenchmark {

    private static final int LEVEL = 1;

    @State(Scope.Benchmark)
    public static class ThroughputState {
        @Param({"1", "8", "64", "512", "4096", "16384", "65536"})
        private int chunkSize;

        private byte[] data;

        @Setup()
        public void setup() throws IOException {
            try (InputStream is = getClass().getResourceAsStream("/dataset-formatted.xml")) {
                this.data = is.readAllBytes();
            }
        }
    }

    @Benchmark
    public void compressionThroughput(ThroughputState state) throws IOException {
        try (ZstdOutputStream out = new ZstdOutputStream(OutputStream.nullOutputStream(), LEVEL)) {
            byte[] data = state.data;
            int chunkSize = state.chunkSize;
            for (int off = 0; off < data.length; off += chunkSize) {
                out.write(data, off, Math.min(chunkSize, data.length - off));
            }
        }
    }

    @Benchmark
    public void createAndClose() throws IOException {
        try (ZstdOutputStream out = new ZstdOutputStream(OutputStream.nullOutputStream(), LEVEL)) {
            // no writes — isolates construction/teardown cost only
        }
    }
}