"""Unix worker limits; parent process deadlines remain enforced on every platform."""

import sys


def apply_limits(cpu_seconds, memory_bytes):
    try:
        import resource
    except ImportError:
        # Windows has no resource module. Use Docker/Linux for OS resource ceilings.
        return
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024, 64 * 1024 * 1024))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
