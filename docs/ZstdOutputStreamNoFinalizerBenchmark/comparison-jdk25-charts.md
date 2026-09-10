# ZstdOutputStreamNoFinalizerBenchmark benchmark comparison — JDK 25

Every JDK 25 implementation is shown. Bar lengths are proportional to the measured value within each workload row, with the worst result as the longest bar. Labels show the absolute value and change versus JDK 25 `orig`; negative percentages mean less execution time or allocation and are better.

![Relative execution cost bar chart](comparison-jdk25-performance.svg)

![Relative on-heap allocation bar chart](comparison-jdk25-heap.svg)

![Relative estimated native allocation bar chart](comparison-jdk25-native.svg)
