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
