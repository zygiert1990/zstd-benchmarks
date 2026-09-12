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
NATIVE_PROFILE_BENCHMARK_SUFFIX = "Throughput"
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
class NativeProfile:
    path: Path
    allocated_bytes: int
    samples: int


@dataclass
class Variant:
    label: str
    jdk: str
    prefix: str
    jmh_path: Path
    rows: dict[RowKey, Measurement]
    parameter_names: tuple[str, ...]
    native_profiles: dict[str, NativeProfile]
    flame_paths: dict[str, Path]

    @property
    def native_path(self) -> Path:
        return self.native_profiles[NATIVE_PROFILE_PARAMETER].path

    @property
    def flame_path(self) -> Path:
        return self.flame_paths[NATIVE_PROFILE_PARAMETER]

    @property
    def native_bytes(self) -> int:
        return self.native_profiles[NATIVE_PROFILE_PARAMETER].allocated_bytes

    @property
    def native_samples(self) -> int:
        return self.native_profiles[NATIVE_PROFILE_PARAMETER].samples


@dataclass(frozen=True)
class ImplementationMetadata:
    label: str
    url: str | None = None


@dataclass(frozen=True)
class HostMetadata:
    os: str
    architecture: str
    cpu: str
    cores: str
    ram: str


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


def parse_parameter_names(path: Path) -> tuple[str, ...]:
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if parts and parts[0] == "Benchmark" and "Mode" in parts:
            mode_index = parts.index("Mode")
            return tuple(part.removeprefix("(").removesuffix(")") for part in parts[1:mode_index])
    raise ValueError(f"No JMH result header found in {path}")


def parse_native(path: Path) -> tuple[int, int]:
    rows = re.findall(
        r"^\s*(\d+)\s+[\d.]+%\s+(\d+)\s+\S+\s*$",
        path.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if not rows:
        raise ValueError(f"No native-memory allocation rows found in {path}")
    return sum(int(row[0]) for row in rows), sum(int(row[1]) for row in rows)


def discover(directory: Path) -> list[Variant]:
    variants: list[Variant] = []
    problems: list[str] = []
    for jdk_dir in sorted(path for path in directory.iterdir() if path.is_dir() and path.name.startswith("jdk-")):
        for variant_dir in sorted(path for path in jdk_dir.iterdir() if path.is_dir()):
            jmh_path = variant_dir / "results.txt"
            if not jmh_path.is_file():
                problems.append(f"missing {jmh_path.relative_to(directory)}")
                continue
            rows = parse_jmh(jmh_path)
            chunk_sizes = sorted(
                {
                    key.params[0]
                    for key in rows
                    if is_primary(key)
                    and base_name(key.benchmark).endswith(NATIVE_PROFILE_BENCHMARK_SUFFIX)
                    and len(key.params) == 1
                    and key.params[0] != "N/A"
                },
                key=lambda value: int(value),
            )
            if not chunk_sizes:
                problems.append(f"no chunked *{NATIVE_PROFILE_BENCHMARK_SUFFIX} rows in {jmh_path.relative_to(directory)}")
                continue
            native_profiles: dict[str, NativeProfile] = {}
            flame_paths: dict[str, Path] = {}
            for chunk_size in chunk_sizes:
                chunk_dir = variant_dir / f"chunk-{chunk_size}"
                native_path = chunk_dir / "summary-nativemem.txt"
                flame_path = chunk_dir / "flame-cpu-forward.html"
                if not native_path.is_file():
                    problems.append(f"missing {native_path.relative_to(directory)}")
                else:
                    allocated_bytes, samples = parse_native(native_path)
                    native_profiles[chunk_size] = NativeProfile(native_path, allocated_bytes, samples)
                if not flame_path.is_file():
                    problems.append(f"missing {flame_path.relative_to(directory)}")
                else:
                    flame_paths[chunk_size] = flame_path
            if len(native_profiles) != len(chunk_sizes) or len(flame_paths) != len(chunk_sizes):
                continue
            variants.append(
                Variant(
                    label=f"{jdk_dir.name} / {variant_dir.name}",
                    jdk=jdk_dir.name,
                    prefix=variant_dir.name,
                    jmh_path=jmh_path,
                    rows=rows,
                    parameter_names=parse_parameter_names(jmh_path),
                    native_profiles=native_profiles,
                    flame_paths=flame_paths,
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
                r"^`orig`\s+results\s+(?:are\s+related\s+to|use\s+(?:local\s+)?artifact)\s+`([^`]+)`\.?\s*$",
                text, re.MULTILINE | re.IGNORECASE,
            )
            if len(matches) == 1:
                metadata[prefix] = ImplementationMetadata(matches[0])
            else:
                problems.append(f"expected one zstd-jni version mapping for `orig`, found {len(matches)}")
            continue
        pattern = (
            rf"^`{re.escape(prefix)}`\s+results\s+(?:use\s+artifact\s+`[^`]+`\s+built\s+from\s+|are\s+based\s+on\s+)branch:\s*"
            r"\[([^\]]+)\]\((https://github\.com/[^)]+)\)\.?\s*$"
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


def parse_input_file_size(directory: Path) -> int | None:
    text = (directory / "readme.md").read_text(encoding="utf-8")
    matches = re.findall(
        r"^(?:Test file to compress|Test dataset) has\s+`([\d,]+)\s+bytes`\.?\s*$",
        text,
        re.MULTILINE | re.IGNORECASE,
    )
    if len(matches) > 1:
        raise ValueError(f"Expected at most one test-file-size mapping in {directory / 'readme.md'}")
    return int(matches[0].replace(",", "")) if matches else None


def parse_host_metadata(directory: Path) -> HostMetadata:
    readme_path = directory.parent / "readme.md"
    text = readme_path.read_text(encoding="utf-8")
    fields = {
        "os": "OS",
        "architecture": "architecture",
        "cpu": "CPU",
        "cores": "CPU cores",
        "ram": "RAM",
    }
    values: dict[str, str] = {}
    problems: list[str] = []
    for field, label in fields.items():
        matches = re.findall(
            rf"^Benchmark host {re.escape(label)}:\s*`([^`]+)`\s*$",
            text,
            re.MULTILINE | re.IGNORECASE,
        )
        if len(matches) == 1:
            values[field] = matches[0]
        else:
            problems.append(f"expected one `Benchmark host {label}` entry, found {len(matches)}")
    if problems:
        raise ValueError(
            f"Invalid benchmark host metadata in {readme_path}:\n- " + "\n- ".join(problems)
        )
    return HostMetadata(**values)


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


def matching_native_time(variant: Variant, chunk_size: str) -> Measurement:
    matches = [
        measurement
        for key, measurement in variant.rows.items()
        if is_primary(key)
        and base_name(key.benchmark).endswith(NATIVE_PROFILE_BENCHMARK_SUFFIX)
        and key.params == (chunk_size,)
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one *{NATIVE_PROFILE_BENCHMARK_SUFFIX} row with parameter "
            f"{chunk_size} in {variant.jmh_path}, found {len(matches)}"
        )
    measurement = matches[0]
    if measurement.mode not in LOWER_IS_FASTER or measurement.unit != "us/op":
        raise ValueError(f"Native normalization requires a time score in us/op: {variant.jmh_path}")
    return measurement


def native_bytes_per_op(
    variant: Variant,
    native_seconds: float,
    chunk_size: str = NATIVE_PROFILE_PARAMETER,
) -> float:
    time = matching_native_time(variant, chunk_size)
    return (
        variant.native_profiles[chunk_size].allocated_bytes
        * time.score
        / (native_seconds * 1_000_000.0)
    )


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
        f"Estimated native `B/op` = sampled allocation bytes × matching JMH `*{NATIVE_PROFILE_BENCHMARK_SUFFIX}` "
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
    parameter_names = variants[0].parameter_names
    if any(variant.parameter_names != parameter_names for variant in variants[1:]):
        raise ValueError("JMH parameter names differ between compared variants")
    for key in common_primary_keys(variants):
        if key.params and key.params != ("N/A",):
            named_params = []
            for index, value in enumerate(key.params):
                name = parameter_names[index] if index < len(parameter_names) else f"parameter{index + 1}"
                unit = " byte" if name == "chunkSize" and value == "1" else " bytes" if name == "chunkSize" else ""
                named_params.append(f"{name}={value}{unit}")
            params = ", ".join(named_params)
        else:
            params = ""
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
    high = 100.0
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

    for tick_index in range(5):
        tick_value = low + span * tick_index / 4
        x = left + plot_width * tick_index / 4
        parts.extend([
            f'<line x1="{x:.1f}" y1="{top - 12}" x2="{x:.1f}" y2="{height - 48}" stroke="#e5e7eb"/>',
            f'<text x="{x:.1f}" y="{height - 25}" text-anchor="middle" class="tick">{tick_value:.0f}%</text>',
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

    native_chunks = sorted(
        set.intersection(*(set(variant.native_profiles) for variant in variants)),
        key=int,
    )
    if not native_chunks:
        raise ValueError("No native-memory chunk profiles are common to all variants")
    native_bars: dict[str, list[float]] = {variant.label: [] for variant in variants}
    native_labels: dict[str, list[str]] = {variant.label: [] for variant in variants}
    for chunk_size in native_chunks:
        native_values = {
            variant.label: native_bytes_per_op(variant, native_seconds, chunk_size)
            for variant in variants
        }
        worst_native = max(native_values.values())
        best_native = min(native_values.values())
        baseline_native = native_values[baseline.label]
        for variant in variants:
            value = native_values[variant.label]
            native_bars[variant.label].append(value / worst_native * 100.0)
            native_labels[variant.label].append(
                f"{'★ ' if math.isclose(value, best_native) else ''}"
                f"{fmt_number(value)} B/op "
                f"({fmt_consumption_delta((value / baseline_native - 1.0) * 100.0)})"
            )
    performance_path = directory / "comparison-jdk25-performance.svg"
    heap_path = directory / "comparison-jdk25-heap.svg"
    native_path = directory / "comparison-jdk25-native.svg"
    labels = [label for _, label in categories]
    native_categories = [
        f"chunkSize={chunk_size} {'byte' if chunk_size == '1' else 'bytes'}"
        for chunk_size in native_chunks
    ]
    render_bar_chart(performance_path, "Execution time (bar length relative to row worst)", variants, labels, performance_bars, performance_labels)
    render_bar_chart(heap_path, "On-heap allocation (bar length relative to row worst)", variants, labels, heap_bars, heap_labels)
    render_bar_chart(native_path, "Estimated native allocation", variants, native_categories, native_bars, native_labels)
    return [performance_path, heap_path, native_path]


def generate_chart_report(
    directory: Path,
    chart_paths: list[Path],
    variants: list[Variant],
    metadata: dict[str, ImplementationMetadata],
    input_file_size: int | None,
    host: HostMetadata,
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
        *([f"Input file: **{input_file_size:,} bytes**.", ""] if input_file_size is not None else []),
        f"Benchmark host: **{host.os}** ({host.architecture}); **{host.cpu}**, "
        f"{host.cores} CPU cores; **{host.ram} RAM**.",
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
    parser.add_argument("--native-seconds", type=float, default=15.0)
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
    input_file_size = parse_input_file_size(directory)
    host_metadata = parse_host_metadata(directory)
    chart_paths = generate_jdk25_charts(directory, jdk25_variants, jdk25_baseline, args.native_seconds)
    jdk25_charts_output.write_text(
        generate_chart_report(
            directory,
            chart_paths,
            jdk25_variants,
            implementation_metadata,
            input_file_size,
            host_metadata,
        ),
        encoding="utf-8",
    )
    print(jdk25_charts_output)
    for chart_path in chart_paths:
        print(chart_path)


if __name__ == "__main__":
    main()
