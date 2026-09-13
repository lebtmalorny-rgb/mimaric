import os
import uuid
import pytest
from fake_etcd import Etcd

from powerops_evacuation_guard import Guard


@pytest.fixture
def backend(monkeypatch):
    if os.environ.get('POWEROPS_EVACUATION_TEST_ENDPOINT'):
        return None
    server = Etcd()
    monkeypatch.setattr('requests.post', server.post)
    return server


@pytest.fixture
def factory(backend):
    prefix = '/test-evacuation/' + str(uuid.uuid4())
    def make(**kwargs):
        return Guard(os.environ.get('POWEROPS_EVACUATION_TEST_ENDPOINT', 'http://fake:2379'),
                     prefix=prefix, cooldown=kwargs.pop('cooldown', 0), **kwargs)
    return make


@pytest.fixture
def guard(factory):
    g = factory()
    g.initialize('test', 'isolated test namespace')
    return g
