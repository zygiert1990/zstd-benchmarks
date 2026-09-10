#!/usr/bin/env python3
"""Generate a Markdown comparison from one docs/<BenchmarkName> directory."""

from __future__ import annotations

import argparse
import html
import math
import re
from dataclasses import dataclass
from pathlib import Path


MODES = {"avgt", "thrpt", "sample", "ss"}
LOWER_IS_FASTER = {"avgt", "sample", "ss"}
NATIVE_PROFILE_BENCHMARK = "compressionThroughput"
NATIVE_PROFILE_PARAMETER = "64"


@dataclass(frozen=True)
class RowKey:
    benchmark: str
    params: tuple[str, ...]


@dataclass
class Measurement:
    mode: str
    count: int
    score: float
    error: float | None
    unit: str


@dataclass
class Variant:
    label: str
    jdk: str
    prefix: str
    jmh_path: Path
    native_path: Path
    flame_path: Path
    rows: dict[RowKey, Measurement]
    native_bytes: int
    native_samples: int


@dataclass(frozen=True)
class ImplementationMetadata:
    label: str
    url: str | None = None


def parse_jmh(path: Path) -> dict[RowKey, Measurement]:
    rows: dict[RowKey, Measurement] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        mode_index = next((i for i, part in enumerate(parts) if part in MODES), None)
        if mode_index is None or mode_index < 1:
            continue
        try:
            benchmark = parts[0]
            params = tuple(parts[1:mode_index])
            mode = parts[mode_index]
            count = int(parts[mode_index + 1])
            score = float(parts[mode_index + 2])
            if parts[mode_index + 3] == "±":
                error = float(parts[mode_index + 4])
                unit = parts[mode_index + 5]
            else:
                error = None
                unit = parts[mode_index + 3]
        except (IndexError, ValueError):
            continue
        rows[RowKey(benchmark, params)] = Measurement(mode, count, score, error, unit)
    if not rows:
        raise ValueError(f"No JMH result rows found in {path}")
    return rows


def parse_native(path: Path) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8")
    sample_match = re.search(r"^Total samples\s*:\s*(\d+)\s*$", text, re.MULTILINE)
    byte_values = [int(value) for value in re.findall(r"^---\s+(\d+)\s+bytes\s+\(", text, re.MULTILINE)]
    if not sample_match or not byte_values:
        raise ValueError(f"No native-memory summary totals found in {path}")
    return sum(byte_values), int(sample_match.group(1))


def discover(directory: Path) -> list[Variant]:
    variants: list[Variant] = []
    problems: list[str] = []
    for jdk_dir in sorted(path for path in directory.iterdir() if path.is_dir() and path.name.startswith("jdk-")):
        jmh_files = sorted(
            path for path in jdk_dir.glob("*.txt") if not path.name.endswith("-summary-nativemem.txt")
        )
        for jmh_path in jmh_files:
            prefix = jmh_path.stem
            native_path = jdk_dir / f"{prefix}-summary-nativemem.txt"
            flames = sorted(jdk_dir.glob(f"{prefix}-flame-*.html"))
            if not native_path.is_file():
                problems.append(f"missing {native_path.relative_to(directory)}")
            if len(flames) != 1:
                problems.append(
                    f"expected one flamegraph for {jdk_dir.name}/{prefix}, found {len(flames)}"
                )
            if not native_path.is_file() or len(flames) != 1:
                continue
            native_bytes, native_samples = parse_native(native_path)
            variants.append(
                Variant(
                    label=f"{jdk_dir.name} / {prefix}",
                    jdk=jdk_dir.name,
                    prefix=prefix,
                    jmh_path=jmh_path,
                    native_path=native_path,
                    flame_path=flames[0],
                    rows=parse_jmh(jmh_path),
                    native_bytes=native_bytes,
                    native_samples=native_samples,
                )
            )
    if problems:
        raise ValueError("Incomplete result triples:\n- " + "\n- ".join(problems))
    if not variants:
        raise ValueError(f"No complete result triples found in {directory}")
    return variants


def parse_implementation_metadata(
    directory: Path, variants: list[Variant]
) -> dict[str, ImplementationMetadata]:
    readme_path = directory / "readme.md"
    if not readme_path.is_file():
        raise ValueError(f"Missing implementation metadata: {readme_path}")
    text = readme_path.read_text(encoding="utf-8")
    prefixes = sorted({variant.prefix for variant in variants})
    metadata: dict[str, ImplementationMetadata] = {}
    problems: list[str] = []
    for prefix in prefixes:
        if prefix == "orig":
            matches = re.findall(
                r"^`orig`\s+results\s+are\s+related\s+to\s+`([^`]+)`\s*$",
                text,
                re.MULTILINE | re.IGNORECASE,
            )
            if len(matches) == 1:
                metadata[prefix] = ImplementationMetadata(matches[0])
            else:
                problems.append(f"expected one zstd-jni version mapping for `orig`, found {len(matches)}")
            continue
        pattern = (
            rf"^`{re.escape(prefix)}`\s+results\s+are\s+based\s+on\s+branch:\s*"
            r"\[([^\]]+)\]\((https://github\.com/[^)]+)\)\s*$"
        )
        matches = re.findall(pattern, text, re.MULTILINE | re.IGNORECASE)
        if len(matches) == 1:
            branch, url = matches[0]
            metadata[prefix] = ImplementationMetadata(branch, url)
        else:
            problems.append(f"expected one GitHub branch mapping for `{prefix}`, found {len(matches)}")
    if problems:
        raise ValueError("Invalid implementation metadata in readme.md:\n- " + "\n- ".join(problems))
    return metadata


def baseline_variant(variants: list[Variant], preferred_jdk: str) -> Variant:
    candidates = [
        variant
        for variant in variants
        if variant.prefix == "orig" and variant.jdk.startswith(preferred_jdk)
    ]
    return sorted(candidates or variants, key=lambda variant: variant.label)[0]


def base_name(benchmark: str) -> str:
    return benchmark.rsplit(".", 1)[-1].split(":", 1)[0]


def is_primary(key: RowKey) -> bool:
    return ":" not in key.benchmark


def heap_key(key: RowKey) -> RowKey:
    return RowKey(key.benchmark + ":gc.alloc.rate.norm", key.params)


def speedup(value: float, baseline: float, mode: str) -> float:
    if mode in LOWER_IS_FASTER:
        return (baseline / value - 1.0) * 100.0
    return (value / baseline - 1.0) * 100.0


def savings(value: float, baseline: float) -> float:
    return (baseline - value) / baseline * 100.0


def fmt_number(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.1f}"
    return f"{value:.3f}"


def fmt_measurement(measurement: Measurement) -> str:
    value = fmt_number(measurement.score)
    if measurement.error is not None:
        value += f" ± {fmt_number(measurement.error)}"
    return f"{value} {measurement.unit}"


def fmt_delta(value: float) -> str:
    return f"{value:+.2f}%"


def fmt_consumption_delta(value: float) -> str:
    return "0.00%" if math.isclose(value, 0.0, abs_tol=0.00001) else f"{value:+.2f}%"


def parameter_sort_key(params: tuple[str, ...]) -> tuple[tuple[int, float | str], ...]:
    result: list[tuple[int, float | str]] = []
    for value in params:
        try:
            result.append((0, float(value)))
        except ValueError:
            result.append((1, value))
    return tuple(result)


def relative(path: Path, directory: Path) -> str:
    return path.relative_to(directory).as_posix()


def matching_native_time(variant: Variant) -> Measurement:
    matches = [
        measurement
        for key, measurement in variant.rows.items()
        if is_primary(key)
        and base_name(key.benchmark) == NATIVE_PROFILE_BENCHMARK
        and NATIVE_PROFILE_PARAMETER in key.params
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one {NATIVE_PROFILE_BENCHMARK} row with parameter "
            f"{NATIVE_PROFILE_PARAMETER} in {variant.jmh_path}, found {len(matches)}"
        )
    measurement = matches[0]
    if measurement.mode not in LOWER_IS_FASTER or measurement.unit != "us/op":
        raise ValueError(f"Native normalization requires a time score in us/op: {variant.jmh_path}")
    return measurement


def native_bytes_per_op(variant: Variant, native_seconds: float) -> float:
    time = matching_native_time(variant)
    return variant.native_bytes * time.score / (native_seconds * 1_000_000.0)


def variant_name(variant: Variant) -> str:
    version = re.match(r"jdk-(\d+)", variant.jdk)
    jdk = f"JDK {version.group(1)}" if version else variant.jdk
    return f"{jdk} · {variant.prefix}"


def common_primary_keys(variants: list[Variant]) -> list[RowKey]:
    common_primary = set.intersection(*(set(k for k in v.rows if is_primary(k)) for v in variants))
    if not common_primary:
        raise ValueError("No primary JMH rows are common to all variants")
    return sorted(common_primary, key=lambda key: (key.benchmark, parameter_sort_key(key.params)))


def table_header(variants: list[Variant], baseline: Variant, first_column: str = "Parameters") -> list[str]:
    headings = [
        f"**{variant_name(variant)}**" + (" (baseline)" if variant is baseline else "")
        for variant in variants
    ]
    return [
        f"| {first_column} | " + " | ".join(headings) + " |",
        "|---|" + "---:|" * len(variants),
    ]


def score_cell(
    measurement: Measurement,
    baseline: Measurement,
    best: float,
    consumption_deltas: bool,
) -> str:
    value = fmt_number(measurement.score)
    if measurement.error is not None:
        value += f" ± {fmt_number(measurement.error)}"
    if consumption_deltas:
        if measurement.mode in LOWER_IS_FASTER:
            delta = (measurement.score / baseline.score - 1.0) * 100.0
        else:
            delta = (baseline.score / measurement.score - 1.0) * 100.0
        delta_text = fmt_consumption_delta(delta)
    else:
        delta_text = fmt_delta(speedup(measurement.score, baseline.score, measurement.mode))
    value += f" {measurement.unit} ({delta_text})"
    return f"**{value}**" if math.isclose(measurement.score, best) else value


def heap_cell(
    measurement: Measurement | None,
    baseline: Measurement | None,
    best: float | None,
    consumption_deltas: bool,
) -> str:
    if measurement is None or baseline is None:
        return "—"
    delta = (
        fmt_consumption_delta((measurement.score / baseline.score - 1.0) * 100.0)
        if consumption_deltas
        else fmt_delta(savings(measurement.score, baseline.score))
    )
    value = f"{fmt_number(measurement.score)} B/op ({delta})"
    return f"**{value}**" if best is not None and math.isclose(measurement.score, best) else value


def comparison_section(
    title: str,
    variants: list[Variant],
    baseline: Variant,
    native_seconds: float,
    consumption_deltas: bool = False,
) -> list[str]:
    lines = [
        f"## {title}",
        "",
        (
            f"Baseline: **{variant_name(baseline)}**. Percentages in parentheses show change in execution cost or allocation; negative is better. Bold marks the best observed value in each row."
            if consumption_deltas
            else f"Baseline: **{variant_name(baseline)}**. Percentages in parentheses are improvement over the baseline; positive is better. Bold marks the best observed value in each row."
        ),
    ]
    keys = common_primary_keys(variants)
    benchmark_names = list(dict.fromkeys(key.benchmark for key in keys))
    for benchmark in benchmark_names:
        benchmark_keys = [key for key in keys if key.benchmark == benchmark]
        mode = variants[0].rows[benchmark_keys[0]].mode
        metric_name = "Execution time" if mode in LOWER_IS_FASTER else "Throughput"
        lines.extend([
            "",
            f"### {base_name(benchmark)} — {metric_name}",
            "",
            "Lower is better." if mode in LOWER_IS_FASTER else "Higher is better.",
            "",
            *table_header(variants, baseline),
        ])
        for key in benchmark_keys:
            measurements = [variant.rows[key] for variant in variants]
            if any(m.mode != mode or m.unit != measurements[0].unit for m in measurements):
                raise ValueError(f"Incompatible JMH modes or units for {key}")
            best = (min if mode in LOWER_IS_FASTER else max)(m.score for m in measurements)
            cells = [score_cell(m, baseline.rows[key], best, consumption_deltas) for m in measurements]
            lines.append(f"| {', '.join(key.params) or '—'} | " + " | ".join(cells) + " |")

        lines.extend([
            "",
            f"### {base_name(benchmark)} — On-heap allocation",
            "",
            "Lower is better.",
            "",
            *table_header(variants, baseline),
        ])
        for key in benchmark_keys:
            measurements = [variant.rows.get(heap_key(key)) for variant in variants]
            available = [measurement.score for measurement in measurements if measurement is not None]
            best = min(available) if available else None
            baseline_measurement = baseline.rows.get(heap_key(key))
            cells = [
                heap_cell(measurement, baseline_measurement, best, consumption_deltas)
                for measurement in measurements
            ]
            lines.append(f"| {', '.join(key.params) or '—'} | " + " | ".join(cells) + " |")

    native_values = {variant.label: native_bytes_per_op(variant, native_seconds) for variant in variants}
    baseline_native = native_values[baseline.label]
    best_native = min(native_values.values())
    native_cells = []
    for variant in variants:
        value = native_values[variant.label]
        delta = (
            fmt_consumption_delta((value / baseline_native - 1.0) * 100.0)
            if consumption_deltas
            else fmt_delta(savings(value, baseline_native))
        )
        cell = f"{fmt_number(value)} B/op ({delta})"
        native_cells.append(f"**{cell}**" if math.isclose(value, best_native) else cell)
    lines.extend([
        "",
        "### Estimated native allocation",
        "",
        "Lower is better. Values are normalized per operation from the native-allocation profile.",
        "",
        *table_header(variants, baseline, "Metric"),
        "| Estimated native allocation | " + " | ".join(native_cells) + " |",
        "| Profiler samples | " + " | ".join(f"{variant.native_samples:,}" for variant in variants) + " |",
    ])
    return lines


def generate(
    directory: Path,
    variants: list[Variant],
    baseline: Variant,
    native_seconds: float,
    scope: str,
    consumption_deltas: bool = False,
) -> str:
    lines = [
        f"# {directory.name} benchmark comparison — {scope}",
        "",
        *comparison_section("Results", variants, baseline, native_seconds, consumption_deltas),
    ]
    lines.extend([
        "",
        "## Native-allocation calculation",
        "",
        f"Estimated native `B/op` = sampled allocation bytes × JMH `{NATIVE_PROFILE_BENCHMARK}` "
        f"time at parameter `{NATIVE_PROFILE_PARAMETER}` ÷ **{native_seconds:g} seconds**. "
        "This is allocation volume per operation, not peak native memory.",
        "",
        "## Artifacts",
        "",
        "| Variant | JMH + GC | Native allocation | CPU flamegraph |",
        "|---|---|---|---|",
    ])
    for variant in variants:
        lines.append(
            f"| {variant.label} | [{variant.jmh_path.name}]({relative(variant.jmh_path, directory)}) | "
            f"[{variant.native_path.name}]({relative(variant.native_path, directory)}) | "
            f"[{variant.flame_path.name}]({relative(variant.flame_path, directory)}) |"
        )

    lines.append("")
    return "\n".join(lines)


def chart_categories(variants: list[Variant]) -> list[tuple[RowKey, str]]:
    categories = []
    for key in common_primary_keys(variants):
        params = ", ".join(key.params) if key.params and key.params != ("N/A",) else ""
        label = base_name(key.benchmark)
        categories.append((key, f"{label} · {params}" if params else label))
    return categories


def render_bar_chart(
    path: Path,
    title: str,
    variants: list[Variant],
    categories: list[str],
    bar_values: dict[str, list[float]],
    bar_labels: dict[str, list[str]],
) -> None:
    plotted = [variant for variant in variants if bar_values.get(variant.label)]
    all_values = [value for variant in plotted for value in bar_values[variant.label]]
    if not plotted or not all_values:
        raise ValueError(f"No values available for chart {title}")
    low = 0.0
    high = max(all_values)
    span = high - low or 1.0
    padding = span * 0.08
    high += padding
    span = high - low

    width = 1200
    left = 300
    right = 250
    top = 105
    row_height = max(58, 24 * len(plotted) + 18)
    height = top + row_height * len(categories) + 75
    plot_width = width - left - right
    origin_x = left
    colors = ["#2563eb", "#ea580c", "#16a34a", "#9333ea", "#0891b2"]

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<style>text{font-family:system-ui,-apple-system,sans-serif;fill:#1f2937}.title{font-size:22px;font-weight:700}.label{font-size:13px}.tick{font-size:12px;fill:#4b5563}.value{font-size:12px;font-weight:600}</style>',
        f'<text x="{left}" y="32" class="title">{html.escape(title)}</text>',
    ]
    legend_x = left
    for index, variant in enumerate(plotted):
        color = colors[index % len(colors)]
        parts.extend([
            f'<rect x="{legend_x}" y="50" width="15" height="15" rx="2" fill="{color}"/>',
            f'<text x="{legend_x + 22}" y="63" class="label">{html.escape(variant_name(variant))}</text>',
        ])
        legend_x += 150

    for tick_index in range(6):
        tick_value = low + span * tick_index / 5
        x = left + plot_width * tick_index / 5
        parts.extend([
            f'<line x1="{x:.1f}" y1="{top - 12}" x2="{x:.1f}" y2="{height - 48}" stroke="#e5e7eb"/>',
            f'<text x="{x:.1f}" y="{height - 25}" text-anchor="middle" class="tick">{tick_value:.1f}%</text>',
        ])
    parts.append(f'<line x1="{origin_x:.1f}" y1="{top - 12}" x2="{origin_x:.1f}" y2="{height - 48}" stroke="#6b7280" stroke-width="1.5"/>')

    bar_height = 18
    for category_index, category in enumerate(categories):
        group_top = top + category_index * row_height
        center_y = group_top + row_height / 2
        parts.append(
            f'<text x="{left - 12}" y="{center_y + 4:.1f}" text-anchor="end" class="label">{html.escape(category)}</text>'
        )
        for variant_index, variant in enumerate(plotted):
            value = bar_values[variant.label][category_index]
            bar_label = bar_labels[variant.label][category_index]
            value_x = left + (value - low) / span * plot_width
            x = origin_x
            bar_width = max(1.0, value_x - origin_x)
            y = center_y + (variant_index - (len(plotted) - 1) / 2) * 23 - bar_height / 2
            color = colors[variant_index % len(colors)]
            label_x = value_x + 6
            parts.extend([
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_height}" rx="2" fill="{color}"/>',
                f'<text x="{label_x:.1f}" y="{y + 13:.1f}" text-anchor="start" class="value">{html.escape(bar_label)}</text>',
            ])
    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def generate_jdk25_charts(
    directory: Path,
    variants: list[Variant],
    baseline: Variant,
    native_seconds: float,
) -> list[Path]:
    categories = chart_categories(variants)
    performance_bars = {variant.label: [] for variant in variants}
    performance_labels: dict[str, list[str]] = {variant.label: [] for variant in variants}
    heap_bars = {variant.label: [] for variant in variants}
    heap_labels: dict[str, list[str]] = {variant.label: [] for variant in variants}
    for key, _ in categories:
        measurements = [variant.rows[key] for variant in variants]
        mode = measurements[0].mode
        if mode in LOWER_IS_FASTER:
            costs = [measurement.score for measurement in measurements]
            baseline_cost = baseline.rows[key].score
        else:
            costs = [1.0 / measurement.score for measurement in measurements]
            baseline_cost = 1.0 / baseline.rows[key].score
        worst_cost = max(costs)
        heap_measurements = [variant.rows[heap_key(key)].score for variant in variants]
        heap_rows = [variant.rows[heap_key(key)] for variant in variants]
        worst_heap = max(heap_measurements)
        best_cost = min(costs)
        best_heap = min(heap_measurements)
        baseline_heap = baseline.rows[heap_key(key)].score
        for variant, cost, heap_value, heap_row in zip(variants, costs, heap_measurements, heap_rows):
            measurement = variant.rows[key]
            performance_delta = (cost / baseline_cost - 1.0) * 100.0
            heap_delta = (heap_value / baseline_heap - 1.0) * 100.0
            performance_bars[variant.label].append(cost / worst_cost * 100.0)
            performance_labels[variant.label].append(
                f"{'★ ' if math.isclose(cost, best_cost) else ''}"
                f"{fmt_measurement(measurement)} ({fmt_consumption_delta(performance_delta)})"
            )
            heap_bars[variant.label].append(heap_value / worst_heap * 100.0)
            heap_labels[variant.label].append(
                f"{'★ ' if math.isclose(heap_value, best_heap) else ''}"
                f"{fmt_measurement(heap_row)} ({fmt_consumption_delta(heap_delta)})"
            )

    native_raw = {variant.label: native_bytes_per_op(variant, native_seconds) for variant in variants}
    worst_native = max(native_raw.values())
    baseline_native = native_raw[baseline.label]
    native_bars = {variant.label: [native_raw[variant.label] / worst_native * 100.0] for variant in variants}
    native_labels = {
        variant.label: [
            f"{'★ ' if math.isclose(native_raw[variant.label], min(native_raw.values())) else ''}"
            f"{fmt_number(native_raw[variant.label])} B/op "
            f"({fmt_consumption_delta((native_raw[variant.label] / baseline_native - 1.0) * 100.0)})"
        ]
        for variant in variants
    }
    performance_path = directory / "comparison-jdk25-performance.svg"
    heap_path = directory / "comparison-jdk25-heap.svg"
    native_path = directory / "comparison-jdk25-native.svg"
    labels = [label for _, label in categories]
    render_bar_chart(performance_path, "Execution time (bar length relative to row worst)", variants, labels, performance_bars, performance_labels)
    render_bar_chart(heap_path, "On-heap allocation (bar length relative to row worst)", variants, labels, heap_bars, heap_labels)
    render_bar_chart(native_path, "Estimated native allocation", variants, ["compressionThroughput · 64"], native_bars, native_labels)
    return [performance_path, heap_path, native_path]


def generate_chart_report(
    directory: Path,
    chart_paths: list[Path],
    variants: list[Variant],
    metadata: dict[str, ImplementationMetadata],
) -> str:
    implementation_items = []
    for variant in variants:
        item = metadata[variant.prefix]
        if variant.prefix == "orig":
            implementation_items.append(f"`orig` — zstd-jni `{item.label}`")
        else:
            implementation_items.append(
                f"`{variant.prefix}` — branch [{item.label}]({item.url})"
            )
    lines = [
        f"# {directory.name} benchmark comparison — JDK 25",
        "",
        "Implementations: " + "; ".join(implementation_items) + ".",
        "",
        "Every JDK 25 implementation is shown. Bar lengths are proportional to the measured value within each workload row, with the worst result as the longest bar. Labels show the absolute value and change versus JDK 25 `orig`; negative percentages mean less execution time or allocation and are better.",
        "",
        f"![Relative execution cost bar chart]({chart_paths[0].name})",
        "",
        f"![Relative on-heap allocation bar chart]({chart_paths[1].name})",
        "",
        f"![Relative estimated native allocation bar chart]({chart_paths[2].name})",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmark_directory", type=Path)
    parser.add_argument("--native-seconds", type=float, default=30.0)
    parser.add_argument("--jdk25-charts-output", type=Path)
    args = parser.parse_args()
    directory = args.benchmark_directory.resolve()
    if not directory.is_dir():
        parser.error(f"not a directory: {directory}")
    if args.native_seconds <= 0:
        parser.error("--native-seconds must be positive")
    variants = sorted(
        discover(directory),
        key=lambda variant: (variant.jdk, variant.prefix != "orig", variant.prefix),
    )
    jdk25_variants = [variant for variant in variants if variant.jdk.startswith("jdk-25")]
    if not jdk25_variants:
        parser.error(f"no JDK 25 results found in {directory}")
    jdk25_charts_output = args.jdk25_charts_output or directory / "comparison-jdk25-charts.md"
    jdk25_baseline = baseline_variant(jdk25_variants, "jdk-25")
    implementation_metadata = parse_implementation_metadata(directory, jdk25_variants)
    chart_paths = generate_jdk25_charts(directory, jdk25_variants, jdk25_baseline, args.native_seconds)
    jdk25_charts_output.write_text(
        generate_chart_report(directory, chart_paths, jdk25_variants, implementation_metadata),
        encoding="utf-8",
    )
    print(jdk25_charts_output)
    for chart_path in chart_paths:
        print(chart_path)


if __name__ == "__main__":
    main()
