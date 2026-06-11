"""Sharding rules in common.config.

`frame_indices_for_pod` (stride sharding) exists because contiguous
ranges are pathologically unbalanced on zoom schedules: per-frame cost
grows with depth (~66× first→last frame measured with the s03 kernel;
portfolio-003 saw a 17× pod-wall-clock imbalance — NEXT_STEPS.md §2).
Striding gives every pod a shallow-to-deep mix.
"""

from __future__ import annotations

import numpy as np
import pytest

from common.config import frame_indices_for_pod, frame_range_for_pod


@pytest.mark.parametrize("n_pods,n_frames", [(1, 7), (4, 600), (8, 1800), (8, 5), (3, 10)])
def test_stride_sharding_is_a_disjoint_cover(n_pods, n_frames):
    seen: list[int] = []
    for pod in range(n_pods):
        seen.extend(frame_indices_for_pod(pod, n_pods, n_frames))
    assert sorted(seen) == list(range(n_frames))


def test_stride_sharding_interleaves():
    assert frame_indices_for_pod(0, 4, 10) == [0, 4, 8]
    assert frame_indices_for_pod(1, 4, 10) == [1, 5, 9]
    assert frame_indices_for_pod(3, 4, 10) == [3, 7]


def test_stride_sharding_balances_monotone_cost():
    """Under a geometrically growing per-frame cost (the zoom shape),
    stride sharding keeps every pod within ~25% of the mean, where
    contiguous ranges leave the last pod with the bulk of the work."""
    n_pods, n_frames = 8, 600
    cost = np.geomspace(1.0, 66.0, n_frames)  # measured first→last ratio

    stride_loads = [
        cost[frame_indices_for_pod(p, n_pods, n_frames)].sum() for p in range(n_pods)
    ]
    contiguous_loads = [
        cost[slice(*frame_range_for_pod(p, n_pods, n_frames))].sum() for p in range(n_pods)
    ]
    mean = cost.sum() / n_pods

    assert max(stride_loads) <= 1.25 * mean
    # The makespan win this exists for: contiguous leaves the deep pod
    # far above the mean; striding must beat it decisively.
    assert max(stride_loads) < 0.5 * max(contiguous_loads)
