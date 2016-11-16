# -*- coding: utf-8 -*-
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""This module contains implementation of RPC client for Decapod API.

Decapod client :py:class:`Client` is a simple RPC client and thin wrapper
for the `requests <http://docs.python-requests.org/en/master/>`_ library
which allows end user to work with remote API without worrying about
connections and endpoints.

RPC client itself manages authorization (therefore you have to supply
it with user/password pair on initialization) so there is no need in
explicit session objects but if you do not like that way, you may always
relogin explicitly.

Usage example:

.. code-block:: python

    client = Client(url="http://localhost", login="root", password="root")

This will initialize new client. Initialization does not imply immediate login,
login would be occured thread-safely on the first real method execution.

.. code-block:: python

    users = client.get_users()

This will return end user a list with active users in Decapod.

.. code-block:: json

    [
        {
            "data": {
                "email": "noreply@example.com",
                "full_name": "Root User",
                "login": "root",
                "role_id": "37fb532f-2620-4e0d-80e6-b68ed6988a6d"
            },
            "id": "6567c2ab-54cc-40b7-a811-6147a3f3ea83",
            "initiator_id": null,
            "model": "user",
            "time_deleted": 0,
            "time_updated": 1478865388,
            "version": 1
        }
    ]

Incoming JSON will be parsed. If it is not possible,
:py:exc:`decapodlib.exceptions.DecapodError` will be raised.
"""


from __future__ import absolute_import
from __future__ import unicode_literals

import abc
import inspect
import logging
import socket

import pkg_resources
import requests
import requests.adapters
import six

from decapodlib import auth
from decapodlib import exceptions

try:
    import simplejson as json
except ImportError:
    import json


LOG = logging.getLogger(__name__)
"""Logger."""

VERSION = pkg_resources.get_distribution("decapodlib").version
"""Package version."""


def json_dumps(data):
    """Makes compact JSON dumps.

    :param data: Data which should be encoded to JSON.
    :type data: Any data, suitable for :py:func:`json.dumps`
    :return: Data, encoded to JSON.
    :rtype: str
    :raises ValueError: if data cannot be encoded to JSON.
    """

    return json.dumps(data, separators=(",", ":"))


def make_query_params(**request_params):
    """Makes query string parameters for request.

    The reason to have this function is to exclude parameters which value
    is ``None``.

    :param request_params: Keyword arguments to be used as GET query
        params later.
    :return: Parameters to be encoded for GET query.
    :rtype: dict
    """

    params = {}
    for key, value in six.iteritems(request_params):
        if value is not None:
            params[key] = value

    return params


def json_response(func):
    """Decorator which parses :py:class:`requests.Response` and
    returns unpacked JSON. If ``Content-Type`` of response is not
    ``application/json``, then it returns text.

    :return: Data of :py:class:`requests.Response` from decorated
        function.
    :raises decapodlib.exceptions.DecapodAPIError: if decoding is not possible
        or response status code is not ``200``.
    """

    @six.wraps(func)
    def decorator(*args, **kwargs):
        response = func(*args, **kwargs)

        if isinstance(response, dict):
            return response

        if response.ok:
            content_type = response.headers.get("Content-Type")
            content_type = content_type or "application/json"
            if content_type == "application/json":
                return response.json()
            return response.text

        raise exceptions.DecapodAPIError(response)

    return decorator


def inject_timeout(func):
    """Decorator which injects ``timeout`` parameter into request.

    On client initiation, default timeout is set. This timeout will be
    injected into any request if no explicit parameter is set.

    :return: Value of decorated function.
    """

    @six.wraps(func)
    def decorator(self, *args, **kwargs):
        kwargs.setdefault("timeout", self._timeout)
        return func(self, *args, **kwargs)

    return decorator


def inject_pagination_params(func):
    """Decorator which injects pagination params into function.

    This decorator pops out such parameters as ``page``, ``per_page``,
    ``all_items``, ``filter`` and ``sort_by`` and prepares correct
    ``query_params`` unified parameter which should be used for
    as a parameter of decorated function.

    :return: Value of decorated function.
    """

    @six.wraps(func)
    def decorator(*args, **kwargs):
        params = make_query_params(
            page=kwargs.pop("page", None),
            per_page=kwargs.pop("per_page", None),
            all=kwargs.pop("all_items", None),
            filter=kwargs.pop("filter", None),
            sort_by=kwargs.pop("sort_by", None)
        )

        if "all" in params:
            params["all"] = str(int(bool(params["all"])))
        if "filter" in params:
            params["filter"] = json_dumps(params["filter"])
        if "sort_by" in params:
            params["sort_by"] = json_dumps(params["sort_by"])

        kwargs["query_params"] = params

        return func(*args, **kwargs)

    return decorator


def no_auth(func):
    """Decorator which injects mark that no authentication should
    be performed for this API call.

    :return: Value of decorated function.
    """

    @six.wraps(func)
    def decorator(*args, **kwargs):
        kwargs["auth"] = auth.no_auth
        return func(*args, **kwargs)

    return decorator


def wrap_errors(func):
    """Decorator which logs and catches all errors of decorated function.

    Also wraps all possible errors into :py:exc:`DecapodAPIError` class.

    :return: Value of decorated function.
    :raises decapodlib.exceptions.DecapodError: on any exception in
        decorated function.
    """

    @six.wraps(func)
    def decorator(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            if isinstance(exc, exceptions.DecapodError):
                LOG.error("Error on access to API: %s", exc)
                raise

            LOG.exception("Exception in decapodlib: %s", exc)

            raise exceptions.DecapodAPIError(exc)

    return decorator


def client_metaclass(name, bases, attrs):
    """A client metaclass to create client instances.

    Basically, it just wraps all public methods with
    :py:func:`wrap_errors`/:py:func:`json_response` decorator pair so no
    need to explicitly define those decorators for every method.
    """

    new_attrs = {}
    for key, value in six.iteritems(attrs):
        if not key.startswith("_") and inspect.isfunction(value):
            value = json_response(value)
            value = wrap_errors(value)
            value = inject_timeout(value)
        new_attrs[key] = value

    return type(name, bases, new_attrs)


class HTTPAdapter(requests.adapters.HTTPAdapter):
    """HTTP adapter for client's :py:class:`requests.Session` which injects
    correct User-Agent header for request."""

    USER_AGENT = "decapodlib/{0}".format(VERSION)
    """User agent for :py:class:`decapodlib.client.Client` instance.

    As a rule, it is just ``decapodlib/{version}`` string.
    """

    def add_headers(self, request, **kwargs):
        request.headers["User-Agent"] = self.USER_AGENT
        super(HTTPAdapter, self).add_headers(request, **kwargs)


@six.add_metaclass(abc.ABCMeta)
@six.python_2_unicode_compatible
class Client(object):
    """A base RPC client model.

    :param str url: URL of Decapod API (*without* version prefix like ``/v1``).
    :param str login: Login of user in Decapod.
    :param str password: Password of user in Decapod.
    :param timeout: Timeout for remote requests. If ``None`` is set,
        default socket timeout (e.g which is set by
        :py:func:`socket.setdefaulttimeout`) will be used.
    :param bool verify: If remote URL implies SSL, then using this option
        client will check SSL certificate for validity.
    :param certificate_file: If SSL works with client certificate, this
        option sets the path to such certificate. If ``None`` is set,
        then it implies that no client certificate should be used.

    :type timeout: :py:class:`int` or ``None``
    :type certificate_file: :py:class:`str` or ``None``
    """

    AUTH_CLASS = None
    """Base class for authenication."""

    @staticmethod
    def _prepare_base_url(url):
        """Prepares base url to be used further."""

        url = url.strip().rstrip("/")
        if not url.startswith("http"):
            url = "http://{0}".format(url)

        return url

    def __init__(self, url, login, password, timeout=None, verify=True,
                 certificate_file=None):
        self._url = self._prepare_base_url(url)
        self._login = login
        self._password = password
        self._session = requests.Session()
        self._timeout = timeout or socket.getdefaulttimeout() or None

        adapter = HTTPAdapter()
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

        self._session.verify = bool(verify)
        if verify and certificate_file:
            self._session.cert = certificate_file

        if self.AUTH_CLASS:
            self._session.auth = self.AUTH_CLASS(self)

    def _make_url(self, endpoint):
        """Concatenates base url and endpoint."""

        url = "{0}{1}".format(self._url, endpoint)

        if not url.endswith("/"):
            url += "/"

        return url

    @abc.abstractmethod
    def login(self, **kwargs):
        raise NotImplementedError()

    def __str__(self):
        return "DecapodAPI: url={0!r}, login={1!r}, password={2!r}".format(
            self._url, self._login, "*" * len(self._password)
        )

    def __repr__(self):
        return "<{0}(url={1!r}, login={2!r}, password={3!r})>".format(
            self.__class__.__name__,
            self._url,
            self._login,
            "*" * len(self._password)
        )


@six.add_metaclass(client_metaclass)
class V1Client(Client):
    """Implemetation of :py:class:`decapodlib.client.Client`
    which works with API version 1.

    Please check parameters for :py:class:`decapodlib.client.Client` class.

    .. note::
        All ``**kwargs`` keyword arguments here are the same as
        :py:meth:`requests.Session.request` takes.
    """

    AUTH_CLASS = auth.V1Auth

    def login(self, **kwargs):
        """This methods logins users into API.

        Basically, you do not need to execute this method by yourself,
        client will implicitly execute it when needed.

        This method does ``POST /v1/auth`` endpoint call.

        :return: Model of the Token.
        :rtype: dict
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url(self.AUTH_CLASS.AUTH_URL)
        payload = {
            "username": self._login,
            "password": self._password
        }

        response = self._session.post(url, json=payload, **kwargs)
        return response

    def logout(self, **kwargs):
        """This method logouts users from API (after that security token
        will be deleted).

        Basically, you do not need to execute this method by yourself,
        client will implicitly execute it when needed.

        This method does ``DELETE /v1/auth`` endpoint call.

        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        if not self._session.auth.token:
            return {}

        url = self._make_url(self.AUTH_CLASS.AUTH_URL)

        try:
            return self._session.delete(url, **kwargs)
        except Exception:
            return {}
        finally:
            self._session.auth.revoke_token()

    @inject_pagination_params
    def get_clusters(self, query_params, **kwargs):
        """This method fetches a list of latest cluster models from API.

        By default, only active clusters will be listed.

        This method does ``GET /v1/cluster`` endpoint call.

        :return: List of latest cluster models.
        :rtype: list
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/cluster/")
        return self._session.get(url, params=query_params, **kwargs)

    def get_cluster(self, cluster_id, **kwargs):
        """This method fetches a single cluster model (latest version)
        from API.

        This method does ``GET /v1/cluster/{cluster_id}`` endpoint call.

        :param str cluster_id: UUID4 (:rfc:`4122`) in string form
            of cluster's ID
        :return: Cluster model of latest available version
        :rtype: dict
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/cluster/{0}/".format(cluster_id))
        return self._session.get(url, **kwargs)

    @inject_pagination_params
    def get_cluster_versions(self, cluster_id, query_params, **kwargs):
        """This method fetches a list of all versions for a certain cluster
        model.

        This method does ``GET /v1/cluster/{cluster_id}/version/`` endpoint
        call.

        :param str cluster_id: UUID4 (:rfc:`4122`) in string form
            of cluster's ID
        :return: List of cluster versions for cluster with ID ``cluster_id``.
        :rtype: list
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/cluster/{0}/version/".format(cluster_id))
        return self._session.get(url, params=query_params, **kwargs)

    def get_cluster_version(self, cluster_id, version, **kwargs):
        """This method fetches a certain version of particular cluster model.

        This method does ``GET /v1/cluster/{cluster_id}/version/{version}``
        endpoint call.

        :param str cluster_id: UUID4 (:rfc:`4122`) in string form
            of cluster's ID
        :param int version: The number of version to fetch.
        :return: Cluster model of certain version.
        :rtype: dict
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url(
            "/v1/cluster/{0}/version/{1}/".format(cluster_id, version))
        return self._session.get(url, **kwargs)

    def create_cluster(self, name, **kwargs):
        """This method creates new cluster model.

        This method does ``POST /v1/cluster/`` endpoint call.

        :param str name: Name of the cluster.
        :return: New cluster model.
        :rtype: dict
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/cluster/")
        payload = {
            "name": name
        }

        return self._session.post(url, json=payload, **kwargs)

    def update_cluster(self, model_data, **kwargs):
        """This methods updates cluster model.

        Please be noticed that no real update is performed, just a new
        version of the same cluster is created.

        This method does ``PUT /v1/cluster/`` endpoint call.

        :param dict model_data: Updated model of the cluster.
        :return: Updated cluster model.
        :rtype: dict
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/cluster/{0}/".format(model_data["id"]))
        return self._session.put(url, json=model_data, **kwargs)

    def delete_cluster(self, cluster_id, **kwargs):
        """This methods deletes cluster model.

        Please be noticed that no real delete is performed, cluster
        model is marked as deleted (``time_deleted > 0``) and model will
        be skipped from listing, updates are forbidden.

        This method does ``DELETE /v1/cluster/`` endpoint call.

        :param str cluster_id: UUID4 (:rfc:`4122`) in string form
            of cluster's ID
        :return: Deleted cluster model.
        :rtype: dict
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/cluster/{0}/".format(cluster_id))
        return self._session.delete(url, **kwargs)

    @inject_pagination_params
    def get_executions(self, query_params, **kwargs):
        """This method fetches a list of latest execution models from API.

        This method does ``GET /v1/execution`` endpoint call.

        :return: List of latest execution models.
        :rtype: list
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/execution/")
        return self._session.get(url, params=query_params, **kwargs)

    def get_execution(self, execution_id, **kwargs):
        """This method fetches a single execution model (latest version)
        from API.

        This method does ``GET /v1/execution/{execution_id}`` endpoint call.

        :param str execution_id: UUID4 (:rfc:`4122`) in string form
            of execution's ID
        :return: Execution model of latest available version
        :rtype: dict
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/execution/{0}/".format(execution_id))
        return self._session.get(url, **kwargs)

    @inject_pagination_params
    def get_execution_versions(self, execution_id, query_params, **kwargs):
        """This method fetches a list of all versions for a certain execution
        model.

        This method does ``GET /v1/execution/{execution_id}/version/``
        endpoint call.

        :param str execution_id: UUID4 (:rfc:`4122`) in string form
            of execution's ID
        :return: List of execution versions for execution with
            ID ``execution_id``.
        :rtype: list
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/execution/{0}/version/".format(execution_id))
        return self._session.get(url, params=query_params, **kwargs)

    def get_execution_version(self, execution_id, version, **kwargs):
        """This method fetches a certain version of particular execution model.

        This method does ``GET
        /v1/execution/{execution_id}/version/{version}`` endpoint call.

        :param str execution_id: UUID4 (:rfc:`4122`) in string form
            of execution's ID
        :param int version: The number of version to fetch.
        :return: Execution model of certain version.
        :rtype: dict
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url(
            "/v1/execution/{0}/version/{1}/".format(execution_id, version))
        return self._session.get(url, **kwargs)

    def create_execution(self, playbook_configuration_id,
                         playbook_configuration_version, **kwargs):
        """This method creates new execution model.

        This method does ``POST /v1/execution/`` endpoint call.

        :param str playbook_configuration_id: UUID4 (:rfc:`4122`) in
            string form of playbook configuration's ID.
        :param int playbook_configuration_version: Version of playbook
            configuration model.
        :return: New execution model.
        :rtype: dict
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/execution/")
        payload = {
            "playbook_configuration": {
                "id": playbook_configuration_id,
                "version": playbook_configuration_version
            }
        }

        return self._session.post(url, json=payload, **kwargs)

    def cancel_execution(self, execution_id, **kwargs):
        """This method cancels existing execution.

        This method does ``DELETE /v1/execution/`` endpoint call.

        :param str execution_id: UUID4 (:rfc:`4122`) in string form of
            execution's ID.
        :return: Canceled execution model.
        :rtype: dict
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/execution/")
        return self._session.delete(url, **kwargs)

    @inject_pagination_params
    def get_execution_steps(self, execution_id, query_params, **kwargs):
        """This method fetches step models of the execution.

        This method does ``GET /v1/execution/{execution_id}/steps``
        endpoint call.

        :param str execution_id: UUID4 (:rfc:`4122`) in string form of
            execution's ID.
        :return: List of execution steps.
        :rtype: list
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/execution/{0}/steps/".format(execution_id))
        return self._session.get(url, params=query_params, **kwargs)

    def get_execution_log(self, execution_id, **kwargs):
        """This method fetches text execution log for a certain execution.

        Execution log is a raw Ansible execution log, that one, which
        is generated by :program:`ansible-playbook` program.

        This method does ``GET /v1/execution/{execution_id}/log``
        endpoint call.

        :param str execution_id: UUID4 (:rfc:`4122`) in string form of
            execution's ID.
        :return: List of execution steps.
        :rtype: list
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        kwargs.setdefault("headers", {}).setdefault(
            "Content-Type", "application/json"
        )
        url = self._make_url("/v1/execution/{0}/log/".format(execution_id))

        return self._session.get(url, **kwargs)

    @inject_pagination_params
    def get_playbook_configurations(self, query_params, **kwargs):
        """This method fetches a list of latest playbook configuration models
        from API.

        By default, only active playbook configurations will be listed.

        This method does ``GET /v1/playbook_configuration`` endpoint call.

        :return: List of latest playbook configuration models.
        :rtype: list
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/playbook_configuration/")
        return self._session.get(url, params=query_params, **kwargs)

    def get_playbook_configuration(self, playbook_configuration_id, **kwargs):
        """This method fetches a single playbook configuration model
        (latest version) from API.

        This method does ``GET
        /v1/playbook_configuration/{playbook_configuration_id}``
        endpoint call.

        :param str playbook_configuration_id: UUID4 (:rfc:`4122`) in
            string form of playbook configuration's ID.
        :return: Playbook configuration model of latest available version.
        :rtype: dict
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url(
            "/v1/playbook_configuration/{0}/".format(playbook_configuration_id)
        )
        return self._session.get(url, **kwargs)

    def get_playbook_configuration_versions(self, playbook_configuration_id,
                                            query_params, **kwargs):
        """This method fetches a list of all versions for a certain
        playbook configuration model.

        This method does ``GET
        /v1/playbook_configuration/{playbook_configuration_id}/version/``
        endpoint call.

        :param str playbook_configuration_id: UUID4 (:rfc:`4122`) in
            string form of playbook configuration's ID.
        :return: List of playbook configuration versions for playbook
            configuration with ID ``playbook_configuration_id``.
        :rtype: list
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url(
            "/v1/playbook_configuration/{0}/version/".format(
                playbook_configuration_id))
        return self._session.get(url, params=query_params, **kwargs)

    def get_playbook_configuration_version(self, playbook_configuration_id,
                                           version, **kwargs):

        """This method fetches a certain version of particular playbook
        configuration model.

        This method does ``GET
        /v1/playbook_configuration/{playbook_configuration_id}/version/{version}``
        endpoint call.

        :param str playbook_configuration_id: UUID4 (:rfc:`4122`) in
            string form of playbook configuration's ID
        :param int version: The number of version to fetch.
        :return: Playbook configuration model of certain version.
        :rtype: dict
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url(
            "/v1/playbook_configuration/{0}/version/{1}/".format(
                playbook_configuration_id, version))
        return self._session.get(url, **kwargs)

    def create_playbook_configuration(self, name, cluster_id, playbook,
                                      server_ids, **kwargs):
        """This method creates new playbook configuration model.

        This method does ``POST /v1/playbook_configuration/`` endpoint
        call.

        :param str name: Name of the playbook configuration.
        :param str cluster_id: UUID4 (:rfc:`4122`) in string form
            of cluster's ID
        :param str playbook: ID of playbook to use.
        :param server_ids: List of server UUID4 (:rfc:`4122`) in string
            form of server model IDs.
            :type server_ids: [:py:class:`str`, ...]
        :return: New cluster model.
        :rtype: dict
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/playbook_configuration/")
        payload = {
            "name": name,
            "cluster_id": cluster_id,
            "playbook": playbook,
            "server_ids": list(set(server_ids))
        }

        return self._session.post(url, json=payload, **kwargs)

    def update_playbook_configuration(self, model_data, **kwargs):
        """This method updates playbook configuration model.

        Please be noticed that no real update is performed, just a new
        version of the same playbook configuration is created.

        This method does ``PUT /v1/playbook_configuration/`` endpoint
        call.

        :param dict model_data: Updated model of the playbook configuration.
        :return: Updated playbook configuration model.
        :rtype: dict
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url(
            "/v1/playbook_configuration/{0}/".format(model_data["id"]))
        return self._session.put(url, json=model_data, **kwargs)

    def delete_playbook_configuration(self, playbook_configuration_id,
                                      **kwargs):
        """This method deletes playbook configuration model.

        Please be noticed that no real delete is performed, playbook
        configuration model is marked as deleted (``time_deleted > 0``)
        and model will be skipped from listing, updates are forbidden.

        This method does ``DELETE /v1/playbook_configuration/`` endpoint
        call.

        :param str playbook_configuration_id: UUID4 (:rfc:`4122`) in
            string form of playbook configuration's ID
        :return: Deleted playbook configuration model.
        :rtype: dict
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url(
            "/v1/playbook_configuration/{0}/".format(playbook_configuration_id)
        )
        return self._session.delete(url, **kwargs)

    @inject_pagination_params
    def get_servers(self, query_params, **kwargs):
        """This method fetches a list of latest server models from API.

        By default, only active servers will be listed.

        This method does ``GET /v1/server`` endpoint call.

        :return: List of latest server models.
        :rtype: list
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/server/")
        return self._session.get(url, params=query_params, **kwargs)

    def get_server(self, server_id, **kwargs):
        """This method fetches a single server model (latest version)
        from API.

        This method does ``GET /v1/server/{server_id}`` endpoint call.

        :param str server_id: UUID4 (:rfc:`4122`) in string form
            of server's ID
        :return: Server model of latest available version
        :rtype: dict
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/server/{0}/".format(server_id))
        return self._session.get(url, **kwargs)

    @inject_pagination_params
    def get_server_versions(self, server_id, query_params, **kwargs):
        """This method fetches a list of all versions for a certain server
        model.

        This method does ``GET /v1/server/{server_id}/version/``
        endpoint call.

        :param str server_id: UUID4 (:rfc:`4122`) in string form
            of server's ID
        :return: List of server versions for server with ID ``server_id``.
        :rtype: list
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/server/{0}/version/".format(server_id))
        return self._session.get(url, params=query_params, **kwargs)

    def get_server_version(self, server_id, version, **kwargs):
        """This method fetches a certain version of particular server model.

        This method does ``GET /v1/server/{server_id}/version/{version}``
        endpoint call.

        :param str server_id: UUID4 (:rfc:`4122`) in string form
            of server's ID
        :param int version: The number of version to fetch.
        :return: Server model of certain version.
        :rtype: dict
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url(
            "/v1/server/{0}/version/{1}/".format(server_id, version))
        return self._session.get(url, **kwargs)

    def create_server(self, server_id, host, username, **kwargs):
        """This method creates new server model.

        This method does ``POST /v1/server/`` endpoint call.

        .. warning::

            You should avoid to use this method manually.
            Servers must be discovered using `cloud-init
            <https://cloudinit.readthedocs.io/en/latest/>`_ based
            discovery mechanism.

        :param str server_id: Unique ID of server.
        :param str host: Hostname of the server (should be accessible by
            Decapod). It is better to have FQDN here.
        :param str username: The name of the user for Ansible on this server.
            Decapod will use Ansible which SSH to machine with hostname
            given in ``host`` parameter and that username.
        :return: New server model.
        :rtype: dict
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/server/")
        payload = {
            "id": server_id,
            "host": host,
            "username": username
        }

        return self._session.post(url, json=payload, **kwargs)

    def put_server(self, model_data, **kwargs):
        """This methods updates server model.

        Please be noticed that no real update is performed, just a new
        version of the same server is created.

        This method does ``PUT /v1/server/`` endpoint call.

        :param dict model_data: Updated model of the server.
        :return: Updated server model.
        :rtype: dict
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/server/{0}/".format(model_data["id"]))
        return self._session.put(url, json=model_data, **kwargs)

    def delete_server(self, server_id, **kwargs):
        """This methods deletes server model.

        Please be noticed that no real delete is performed, server
        model is marked as deleted (``time_deleted > 0``) and model will
        be skipped from listing, updates are forbidden.

        This method does ``DELETE /v1/server/`` endpoint call.

        :param str server_id: UUID4 (:rfc:`4122`) in string form
            of server's ID
        :return: Deleted server model.
        :rtype: dict
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/server/{0}/".format(server_id))
        return self._session.delete(url, **kwargs)

    @inject_pagination_params
    def get_users(self, query_params, **kwargs):
        """This method fetches a list of latest user models from API.

        By default, only active users will be listed.

        This method does ``GET /v1/user`` endpoint call.

        :return: List of latest user models.
        :rtype: list
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/user/")
        return self._session.get(url, params=query_params, **kwargs)

    def get_user(self, user_id, **kwargs):
        """This method fetches a single user model (latest version)
        from API.

        This method does ``GET /v1/user/{user_id}`` endpoint call.

        :param str user_id: UUID4 (:rfc:`4122`) in string form
            of user's ID
        :return: User model of latest available version
        :rtype: dict
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/user/{0}/".format(user_id))
        return self._session.get(url, **kwargs)

    @inject_pagination_params
    def get_user_versions(self, user_id, query_params, **kwargs):
        """This method fetches a list of all versions for a certain user
        model.

        This method does ``GET /v1/user/{user_id}/version/`` endpoint
        call.

        :param str user_id: UUID4 (:rfc:`4122`) in string form
            of user's ID
        :return: List of user versions for user with ID ``user_id``.
        :rtype: list
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/user/{0}/version/".format(user_id))
        return self._session.get(url, params=query_params, **kwargs)

    def get_user_version(self, user_id, version, **kwargs):
        """This method fetches a certain version of particular user model.

        This method does ``GET /v1/user/{user_id}/version/{version}``
        endpoint call.

        :param str user_id: UUID4 (:rfc:`4122`) in string form
            of user's ID
        :param int version: The number of version to fetch.
        :return: User model of certain version.
        :rtype: dict
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url(
            "/v1/user/{0}/version/{1}/".format(user_id, version))
        return self._session.get(url, **kwargs)

    def create_user(self, login, email, full_name="", role_id=None, **kwargs):
        """This method creates new user model.

        This method does ``POST /v1/user/`` endpoint call.

        :param str name: Name of the user.
        :return: New user model.
        :rtype: dict
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/user/")
        payload = {
            "login": login,
            "email": email,
            "full_name": full_name,
            "role_id": role_id
        }

        return self._session.post(url, json=payload, **kwargs)

    def update_user(self, model_data, **kwargs):
        """This methods updates user model.

        Please be noticed that no real update is performed, just a new
        version of the same user is created.

        This method does ``PUT /v1/user/`` endpoint call.

        :param dict model_data: Updated model of the user.
        :return: Updated user model.
        :rtype: dict
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/user/{0}/".format(model_data["id"]))
        return self._session.put(url, json=model_data, **kwargs)

    def delete_user(self, user_id, **kwargs):
        """This methods deletes user model.

        Please be noticed that no real delete is performed, user model
        is marked as deleted (``time_deleted > 0``) and model will be
        skipped from listing, updates are forbidden.

        This method does ``DELETE /v1/user/`` endpoint call.

        :param str user_id: UUID4 (:rfc:`4122`) in string form
            of user's ID
        :return: Deleted user model.
        :rtype: dict
        :raises decapodlib.exceptions.DecapodError: if not possible to
            connect to API.
        :raises decapodlib.exceptions.DecapodAPIError: if API returns error
            response.
        """

        url = self._make_url("/v1/user/{0}/".format(user_id))
        return self._session.delete(url, **kwargs)

    @inject_pagination_params
    def get_roles(self, query_params, **kwargs):
        url = self._make_url("/v1/role/")
        return self._session.get(url, params=query_params, **kwargs)

    def get_role(self, role_id, **kwargs):
        url = self._make_url("/v1/role/{0}/".format(role_id))
        return self._session.get(url, **kwargs)

    @inject_pagination_params
    def get_role_versions(self, role_id, query_params, **kwargs):
        url = self._make_url("/v1/role/{0}/version/".format(role_id))
        return self._session.get(url, params=query_params, **kwargs)

    def get_role_version(self, role_id, version, **kwargs):
        url = self._make_url(
            "/v1/role/{0}/version/{1}/".format(role_id, version))
        return self._session.get(url, **kwargs)

    def create_role(self, name, permissions, **kwargs):
        url = self._make_url("/v1/role/")
        payload = {
            "name": name,
            "permissions": permissions
        }

        return self._session.post(url, json=payload, **kwargs)

    def update_role(self, model_data, **kwargs):
        url = self._make_url("/v1/role/{0}/".format(model_data["id"]))
        return self._session.put(url, json=model_data, **kwargs)

    def delete_role(self, role_id, **kwargs):
        url = self._make_url("/v1/role/{0}/".format(role_id))
        return self._session.delete(url, **kwargs)

    def get_permissions(self, **kwargs):
        url = self._make_url("/v1/permission/")
        return self._session.get(url, **kwargs)

    def get_playbooks(self, **kwargs):
        url = self._make_url("/v1/playbook/")
        return self._session.get(url, **kwargs)

    @no_auth
    def get_info(self, **kwargs):
        url = self._make_url("/v1/info/")
        return self._session.get(url, **kwargs)

    @no_auth
    def request_password_reset(self, login, **kwargs):
        url = self._make_url("/v1/password_reset/")
        payload = {"login": login}
        return self._session.post(url, json=payload, **kwargs)

    @no_auth
    def peek_password_reset(self, reset_token, **kwargs):
        url = self._make_url("/v1/password_reset/{0}/".format(reset_token))
        return self._session.get(url, **kwargs)

    @no_auth
    def reset_password(self, reset_token, new_password, **kwargs):
        url = self._make_url("/v1/password_reset/{0}/".format(reset_token))
        payload = {"password": new_password}
        return self._session.post(url, json=payload, **kwargs)
