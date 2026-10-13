"""Timing A* against Dijkstra on increasingly large grids.

The point is not the absolute numbers, which depend on the machine. It is the
gap: both algorithms run the same code path over the same graph for the same
request, differing only in whether a heuristic is supplied, so the difference
in states settled and in wall-clock time is attributable to the heuristic and
nothing else.

Both cost modes are measured, because they do not behave alike. The distance
bound is tight and A* wins clearly. The time bound divides straight-line
distance by the graph's single fastest speed, so where speeds vary widely it
is loose enough that the states it saves barely pay for the trigonometry it
costs -- a real property of the heuristic, not a defect in the measurement.

Usage:
    python -m bench.benchmark
    python -m bench.benchmark --sizes 10 50 100 --repeats 5 --seed 3
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

from routing import CostMode, NoRouteFound, RouteRequest, Router

from tests.fixtures import random_grid_graph

DEFAULT_SIZES = (10, 25, 50, 100)
DEFAULT_REPEATS = 3


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    """One algorithm, one grid size, averaged over the trials that found a route."""

    grid_size: str
    node_count: int
    cost_mode: str
    algorithm: str
    trials: int
    mean_seconds: float
    mean_states_settled: float


def run_benchmark(
    sizes: list[int] | tuple[int, ...] = DEFAULT_SIZES,
    repeats: int = DEFAULT_REPEATS,
    seed: int = 0,
) -> list[BenchmarkResult]:
    """Time both algorithms on a grid of each size.

    A grid whose corners happen to be disconnected by its random closures
    contributes no trial rather than a zero, so a size that never routed shows
    ``trials=0`` instead of a misleadingly fast mean.
    """
    results: list[BenchmarkResult] = []
    for size in sizes:
        graph = random_grid_graph(size, seed=seed)
        router = Router(graph=graph)
        for mode in (CostMode.SHORTEST, CostMode.FASTEST):
            for algorithm, use_astar in (("dijkstra", False), ("astar", True)):
                results.append(
                    _time_one(
                        router,
                        request=RouteRequest(
                            origin="0_0",
                            destination=f"{size - 1}_{size - 1}",
                            cost_mode=mode,
                            use_astar=use_astar,
                        ),
                        algorithm=algorithm,
                        grid_size=f"{size}x{size}",
                        node_count=len(graph),
                        repeats=repeats,
                    )
                )
    return results


def format_results(results: list[BenchmarkResult]) -> str:
    header = (
        f"{'grid':>9}  {'nodes':>6}  {'mode':<9}  {'algorithm':<9}  "
        f"{'mean ms':>8}  {'settled':>8}  {'trials':>6}"
    )
    lines = [header, "-" * len(header)]
    for result in results:
        lines.append(
            f"{result.grid_size:>9}  {result.node_count:>6}  {result.cost_mode:<9}  "
            f"{result.algorithm:<9}  {result.mean_seconds * 1000:>8.2f}  "
            f"{result.mean_states_settled:>8.0f}  {result.trials:>6}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=list(DEFAULT_SIZES))
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--seed", type=int, default=0)
    arguments = parser.parse_args()
    print(format_results(run_benchmark(arguments.sizes, arguments.repeats, arguments.seed)))


# --- Internal --------------------------------------------------------------


def _time_one(
    router: Router,
    *,
    request: RouteRequest,
    algorithm: str,
    grid_size: str,
    node_count: int,
    repeats: int,
) -> BenchmarkResult:
    durations: list[float] = []
    settled: list[int] = []
    for _ in range(repeats):
        started = time.perf_counter()
        try:
            route = router.find(request)
        except NoRouteFound:
            continue
        durations.append(time.perf_counter() - started)
        settled.append(route.nodes_expanded)
    return BenchmarkResult(
        grid_size=grid_size,
        node_count=node_count,
        cost_mode=CostMode(request.cost_mode).value,
        algorithm=algorithm,
        trials=len(durations),
        mean_seconds=sum(durations) / len(durations) if durations else 0.0,
        mean_states_settled=sum(settled) / len(settled) if settled else 0.0,
    )


if __name__ == "__main__":
    main()
