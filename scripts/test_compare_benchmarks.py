import json
import tempfile
import unittest
from pathlib import Path

from compare_benchmarks import discover, generate_jdk25_charts, parse_jmh, RowKey


class ComparisonFormatsTest(unittest.TestCase):
    def test_supported_profile_layouts(self):
        # Exercise complete discovery -> SVG generation for each runner layout.
        for parameter, value, folder, label in [
            ("chunkSize", "64", "chunk-64", "chunkSize=64"),
            ("bufferSize", "262144", "buffer-262144", "bufferSize=262144"),
            (None, "", "default", "Single operation"),
        ]:
            with self.subTest(parameter=parameter), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for name in ["orig", "candidate"]:
                    variant = root / "jdk-25-test" / name
                    profile = variant / folder
                    profile.mkdir(parents=True)
                    header = f"({parameter})" if parameter else ""
                    (variant / "results.txt").write_text(
                        f"Benchmark {header} Mode Cnt Score Error Units\n"
                        f"Example.workThroughput {value} avgt 6 1.0 ± 0.1 us/op\n"
                        f"Example.workThroughput:gc.alloc.rate.norm {value} avgt 6 0.0 ± 0.0 B/op\n"
                    )
                    (profile / "summary-nativemem.txt").write_text("0 0.0% 0 malloc\n")
                    (profile / "flame-cpu-forward.html").write_text("<html></html>")
                    (profile / "results-nativemem.json").write_text(json.dumps([{
                        "benchmark": "Example.workThroughput",
                        "params": {parameter: value} if parameter else {},
                        "mode": "avgt", "measurementIterations": 3,
                        "measurementTime": "5 s",
                        "primaryMetric": {"score": 1.0, "scoreError": 0.1, "scoreUnit": "us/op"},
                    }]))
                variants = discover(root)
                paths = generate_jdk25_charts(root, variants, variants[0])
                self.assertEqual(len(paths), 3)
                self.assertIn(label, paths[2].read_text())
                self.assertTrue(variants[0].native_path.is_file())

                # A stale profile from a different parameter value must fail.
                path = variants[0].native_path.parent / "results-nativemem.json"
                data = json.loads(path.read_text())
                data[0]["params"] = {"chunkSize": "999"}
                path.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, "Expected parameters"):
                    discover(root)

    def test_near_zero_heap_allocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.txt"
            path.write_text("Example.workThroughput:gc.alloc.rate.norm 64 avgt 15 ≈ 10⁻⁴ B/op\n")
            rows = parse_jmh(path)
            self.assertEqual(rows[RowKey("Example.workThroughput:gc.alloc.rate.norm", ("64",))].score, 0.0001)


if __name__ == "__main__":
    unittest.main()
