import itertools

import pytest

from bankagent import pipeline
from bankagent.graph import Agent
from bankagent.identity import IdentityService
from bankagent.policy import PolicyEngine
from bankagent.tools import BankTools

from fixture_data import write_fixture


@pytest.fixture(scope="session")
def serving_db(tmp_path_factory):
    raw = tmp_path_factory.mktemp("raw")
    write_fixture(str(raw))
    db = tmp_path_factory.mktemp("serving") / "serving.duckdb"
    pipeline.run(str(raw), str(db))
    return str(db)


class FakeClock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def env(serving_db):
    clock = FakeClock()
    identity = IdentityService(ttl_seconds=900, clock=clock)
    tools = BankTools(serving_db, identity)
    agent = Agent(tools, PolicyEngine())
    counter = itertools.count()

    class Env:
        pass

    e = Env()
    e.clock, e.identity, e.tools, e.agent = clock, identity, tools, agent
    e.login = identity.login
    e.thread = lambda: f"t{next(counter)}"
    return e


# Perfiles de Hypothesis (tests/test_properties.py). CI usa "ci": acotado y determinista (sin flakes, mismo
# resultado en cada corrida). "deep" se corre a mano y sus números van a docs/threat-model.md:
#     HYPOTHESIS_PROFILE=deep pytest tests/test_properties.py -q -s
import os  # noqa: E402

from hypothesis import HealthCheck, settings  # noqa: E402

_common = dict(deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large,
                                                      HealthCheck.filter_too_much], stateful_step_count=20)
settings.register_profile("ci", max_examples=200, derandomize=True, print_blob=True, **_common)
settings.register_profile("deep", max_examples=5000, print_blob=True, **_common)
settings.register_profile("dev", max_examples=30, **_common)
settings.register_profile("stats", max_examples=300, print_blob=True, **_common)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))
