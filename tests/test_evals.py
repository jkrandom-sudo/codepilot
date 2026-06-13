from types import SimpleNamespace

from evals.analyze_traces import compute_metrics


def _run(**kwargs):
    defaults = {
        "metadata": {},
        "total_tokens": 100,
        "latency": 2.0,
        "error": None,
        "extra": {},
        "trace_id": "trace-1",
        "id": "run-1",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class FakeClient:
    def __init__(self):
        self.calls = 0

    def list_runs(self, **kwargs):
        self.calls += 1
        return [
            SimpleNamespace(name="read_file", run_type="tool"),
            SimpleNamespace(name="grep", run_type="tool"),
            SimpleNamespace(name="agent", run_type="chain"),
        ]


def test_compute_metrics_uses_task_metrics_without_child_lookup():
    client = FakeClient()
    run = _run(extra={
        "task_metrics": {
            "iteration_count": 2,
            "tool_distribution": {"read_file": 1, "grep": 1},
        }
    })

    metrics = compute_metrics([run], client, "project-id")

    assert client.calls == 0
    assert metrics["avg_iterations"] == 2
    assert metrics["tool_distribution"] == {"read_file": 1, "grep": 1}


def test_compute_metrics_does_not_fetch_children_by_default():
    client = FakeClient()
    metrics = compute_metrics([_run()], client, "project-id")

    assert client.calls == 0
    assert metrics["avg_iterations"] == 0
    assert metrics["tool_distribution"] == {}


def test_compute_metrics_child_lookup_is_opt_in():
    client = FakeClient()
    metrics = compute_metrics([_run()], client, "project-id", include_child_runs=True)

    assert client.calls == 1
    assert metrics["avg_iterations"] == 2
    assert metrics["tool_distribution"] == {"read_file": 1, "grep": 1}
