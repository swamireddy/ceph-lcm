# -*- coding: utf-8 -*-
"""Tests for cephlcm.common.models.playbook_configuration."""


import unittest.mock

import pytest

from cephlcm.common import plugins
from cephlcm.common.models import cluster
from cephlcm.common.models import playbook_configuration
from cephlcm.common.models import server


@pytest.fixture
def new_cluster(configure_model):
    clstr = cluster.ClusterModel.create(
        pytest.faux.gen_alphanumeric()
    )

    return clstr


@pytest.fixture
def new_servers(configure_model):
    servers = []

    for _ in range(3):
        srv = server.ServerModel.create(
            pytest.faux.gen_alphanumeric(),
            pytest.faux.gen_alphanumeric(),
            pytest.faux.gen_alphanumeric(),
            pytest.faux.gen_ipaddr(),
            initiator_id=pytest.faux.gen_uuid()
        )
        servers.append(srv)

    return servers


@pytest.yield_fixture
def playbook_name():
    name = pytest.faux.gen_alphanumeric()
    mocked_plugin = unittest.mock.MagicMock()
    mocked_plugin.PUBLIC = True

    patch = unittest.mock.patch(
        "cephlcm.common.plugins.get_playbook_plugins",
        return_value={name: mocked_plugin}
    )

    with patch:
        yield name


@pytest.fixture
def configuration():
    return {
        pytest.faux.gen_alpha(): pytest.faux.gen_alphanumeric(),
    }


def test_create(new_cluster, new_servers, playbook_name, pymongo_connection,
                freeze_time):
    name = pytest.faux.gen_alpha()
    pcmodel = playbook_configuration.PlaybookConfigurationModel.create(
        name=name,
        playbook=playbook_name,
        cluster=new_cluster,
        servers=new_servers,
        initiator_id=pytest.faux.gen_uuid()
    )

    db_pc = pymongo_connection.db.playbook_configuration.find_one(
        {"_id": pcmodel._id}
    )

    assert db_pc
    assert pcmodel.name == db_pc["name"]
    assert pcmodel.playbook == db_pc["playbook"]
    assert pcmodel.server_ids == db_pc["server_ids"]
    assert pcmodel.configuration == db_pc["configuration"]
    assert pcmodel.cluster_id == db_pc["cluster_id"]
    assert pcmodel.model_id == db_pc["model_id"]
    assert pcmodel.version == db_pc["version"]
    assert pcmodel.time_created == db_pc["time_created"]
    assert pcmodel.time_deleted == db_pc["time_deleted"]
    assert pcmodel.initiator_id == db_pc["initiator_id"]

    assert pcmodel.name == name
    assert pcmodel.playbook == playbook_name
    assert pcmodel.cluster.model_id == new_cluster.model_id
    assert pcmodel.server_ids == [srv.model_id for srv in new_servers]
    assert pcmodel.version == 1
    assert pcmodel.time_created == int(freeze_time.return_value)
    assert pcmodel.time_deleted == 0

    assert pcmodel.cluster.model_id == pcmodel.cluster_id
    assert pcmodel.server_ids == [srv.model_id for srv in pcmodel.servers]


def test_update(new_cluster, new_servers, playbook_name, pymongo_connection,
                freeze_time):
    name = pytest.faux.gen_alpha()
    pcmodel = playbook_configuration.PlaybookConfigurationModel.create(
        name=name,
        playbook=playbook_name,
        cluster=new_cluster,
        servers=new_servers,
        initiator_id=pytest.faux.gen_uuid()
    )
    old_name = pcmodel.name

    pcmodel.name = pytest.faux.gen_alpha()
    pcmodel.save()

    assert pcmodel.version == 2
    assert pcmodel.name != old_name


def test_delete(new_cluster, new_servers, playbook_name, pymongo_connection,
                freeze_time):
    pcmodel = playbook_configuration.PlaybookConfigurationModel.create(
        name=pytest.faux.gen_alpha(),
        playbook=playbook_name,
        cluster=new_cluster,
        servers=new_servers,
        initiator_id=pytest.faux.gen_uuid()
    )
    pcmodel.delete()

    assert pcmodel.version == 2
    assert pcmodel.time_deleted == int(freeze_time.return_value)
