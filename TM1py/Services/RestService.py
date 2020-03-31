# -*- coding: utf-8 -*-
import functools
import sys
import warnings
from base64 import b64encode, b64decode

import requests
from requests import Timeout
from requests.adapters import HTTPAdapter

# SSO not supported for Linux
from TM1py.Exceptions.Exceptions import TM1pyTimeout

try:
    from requests_negotiate_sspi import HttpNegotiateAuth
except ImportError:
    warnings.warn("requests_negotiate_sspi failed to import. SSO will not work", ImportWarning)

from TM1py.Exceptions import TM1pyException

# import Http-Client depending on python version
if sys.version[0] == '2':
    import httplib as http_client
else:
    import http.client as http_client


def httpmethod(func):
    """ Higher Order Function to wrap the GET, POST, PATCH, PUT, DELETE methods
        Takes care of:
        - encoding of url and payload
        - verifying response. Throws TM1pyException if StatusCode of Response is not OK
    """

    @functools.wraps(func)
    def wrapper(self, url, data='', encoding='utf-8', **kwargs):
        # request encoding
        url, data = self._url_and_body(
            url=url,
            data=data,
            encoding=encoding)
        # execute request
        try:
            response = func(self, url, data, **kwargs)
            # verify
            self.verify_response(response=response)
            # response encoding
            response.encoding = encoding
            return response
        except Timeout:
            raise TM1pyTimeout(method=func.__name__, url=url, timeout=kwargs['timeout'])

    return wrapper


class RestService:
    """ Low level communication with TM1 instance through HTTP.
        Allows to execute HTTP Methods
            - GET
            - POST
            - PATCH
            - DELETE
        Takes Care of
            - Encodings
            - TM1 User-Login
            - HTTP Headers
            - HTTP Session Management
            - Response Handling
        Based on requests module
    """

    HEADERS = {'Connection': 'keep-alive',
               'User-Agent': 'TM1py',
               'Content-Type': 'application/json; odata.streaming=true; charset=utf-8',
               'Accept': 'application/json;odata.metadata=none,text/plain',
               'TM1-SessionContext': 'TM1py'}

    def __init__(self, **kwargs):
        """ Create an instance of RESTService
        :param address: String - address of the TM1 instance
        :param port: Int - HTTPPortNumber as specified in the tm1s.cfg
        :param base_url - base url e.g. https://localhost:12354/api/v1
        :param user: String - name of the user
        :param password String - password of the user
        :param decode_b64 - whether password argument is b64 encoded
        :param namespace String - optional CAM namespace
        :param ssl: boolean -  as specified in the tm1s.cfg
        :param session_id: String - TM1SessionId e.g. q7O6e1w49AixeuLVxJ1GZg
        :param session_context: String - Name of the Application. Controls "Context" column in Arc / TM1top.
        If None, use default: TM1py
        :param verify: path to .cer file or 'False' / False (if no ssl verification is required)
        :param logging: boolean - switch on/off verbose http logging into sys.stdout
        :param timeout: Float - Number of seconds that the client will wait to receive the first byte.
        :param connection_pool_size - In a multithreaded environment, you should set this value to a
        higher number, such as the number of threads
        """
        self._ssl = self.translate_to_boolean(kwargs['ssl'])
        self._address = kwargs.get('address', None)
        self._port = kwargs.get('port', None)
        self._verify = False
        self._timeout = kwargs.get('timeout', None)

        if 'verify' in kwargs:
            if isinstance(kwargs['verify'], str):
                if kwargs['verify'].upper() != 'FALSE':
                    self._verify = kwargs.get('verify')

        if 'base_url' in kwargs:
            self._base_url = kwargs['base_url']
        else:
            self._base_url = "http{}://{}:{}".format(
                's' if self._ssl else '',
                'localhost' if len(self._address) == 0 else self._address,
                self._port)

        self._version = None
        self._headers = self.HEADERS.copy()
        if "session_context" in kwargs:
            self._headers["TM1-SessionContext"] = kwargs["session_context"]

        self.disable_http_warnings()
        # re-use or create tm1 http session
        self._s = requests.session()
        if "session_id" in kwargs:
            self._s.cookies.set("TM1SessionId", kwargs["session_id"])
            self.set_version()
        else:
            self._start_session(
                user=kwargs.get("user", None),
                password=kwargs.get("password", None),
                namespace=kwargs.get("namespace", None),
                gateway=kwargs.get("gateway", None),
                decode_b64=self.translate_to_boolean(kwargs.get("decode_b64", False)))

        # manage connection pool
        if "connection_pool_size" in kwargs:
            self._manage_http_connection_pool(kwargs.get("connection_pool_size"))

        # Logging
        if 'logging' in kwargs:
            if self.translate_to_boolean(value=kwargs['logging']):
                http_client.HTTPConnection.debuglevel = 1

    def _manage_http_connection_pool(self, connection_pool_size):
        self._s.mount(
            self._base_url,
            HTTPAdapter(
                pool_connections=int(connection_pool_size),
                pool_maxsize=int(connection_pool_size)))

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        self.logout()

    @httpmethod
    def GET(self, url, data='', headers=None, timeout=None, **kwargs):
        """ Perform a GET request against TM1 instance
        :param url:
        :param data: the payload
        :param headers: custom headers
        :param timeout: Number of seconds that the client will wait to receive the first byte.
        :return: response object
        """
        return self._s.get(
            url=url,
            headers={**self._headers, **headers} if headers else self._headers,
            data=data,
            verify=self._verify,
            timeout=timeout if timeout else self._timeout)

    @httpmethod
    def POST(self, url, data, headers=None, timeout=None, **kwargs):
        """ POST request against the TM1 instance
        :param url:
        :param data: the payload
        :param headers: custom headers
        :param timeout: Number of seconds that the client will wait to receive the first byte.
        :return: response object
        """
        return self._s.post(
            url=url,
            headers={**self._headers, **headers} if headers else self._headers,
            data=data,
            verify=self._verify,
            timeout=timeout if timeout else self._timeout)

    @httpmethod
    def PATCH(self, url, data, headers=None, timeout=None, **kwargs):
        """ PATCH request against the TM1 instance
        :param url: String, for instance : /api/v1/Dimensions('plan_business_unit')
        :param data: the payload
        :param headers: custom headers
        :param timeout: Number of seconds that the client will wait to receive the first byte.
        :return: response object
        """
        return self._s.patch(
            url=url,
            headers={**self._headers, **headers} if headers else self._headers,
            data=data,
            verify=self._verify,
            timeout=timeout if timeout else self._timeout)

    @httpmethod
    def PUT(self, url, data, headers=None, timeout=None, **kwargs):
        """ PUT request against the TM1 instance
        :param url: String, for instance : /api/v1/Dimensions('plan_business_unit')
        :param data: the payload
        :param headers: custom headers
        :param timeout: Number of seconds that the client will wait to receive the first byte.
        :return: response object
        """
        return self._s.put(
            url=url,
            headers={**self._headers, **headers} if headers else self._headers,
            data=data,
            verify=self._verify,
            timeout=timeout if timeout else self._timeout)

    @httpmethod
    def DELETE(self, url, data='', headers=None, timeout=None, **kwargs):
        """ Delete request against TM1 instance
        :param url:  String, for instance : /api/v1/Dimensions('plan_business_unit')
        :param data: the payload
        :param headers: custom headers
        :param timeout: Number of seconds that the client will wait to receive the first byte.
        :return: response object
        """
        return self._s.delete(
            url=url,
            headers={**self._headers, **headers} if headers else self._headers,
            data=data,
            verify=self._verify,
            timeout=timeout if timeout else self._timeout)

    def logout(self):
        """ End TM1 Session and HTTP session
        """
        self._headers["Connection"] = "close"
        # Easier to ask for forgiveness than permission
        try:
            # ProductVersion >= TM1 10.2.2 FP 6
            self.POST('/api/v1/ActiveSession/tm1.Close', '')
        except TM1pyException:
            # ProductVersion < TM1 10.2.2 FP 6
            self.POST('/api/logout', '')
        self._s.close()

    def _start_session(self, user, password, decode_b64=False, namespace=None, gateway=None):
        """ perform a simple GET request (Ask for the TM1 Version) to start a session
        """
        # Authorization [Basic, CAM] through Headers
        token = self._build_authorization_token(
            user,
            self.b64_decode_password(password) if decode_b64 else password,
            namespace,
            gateway,
            self._verify)
        self.add_http_header('Authorization', token)
        url = '/api/v1/Configuration/ProductVersion/$value'
        try:
            response = self.GET(url=url)
            self._version = response.text
        finally:
            # After we have session cookie, drop the Authorization Header
            self.remove_http_header('Authorization')

    def _url_and_body(self, url, data, encoding='utf-8'):
        """ create proper url and payload
        """
        url = self._base_url + url
        url = url.replace(' ', '%20').replace('#', '%23')
        if isinstance(data, str):
            data = data.encode(encoding)
        return url, data

    def is_connected(self):
        """ Check if Connection to TM1 Server is established.
        :Returns:
            Boolean
        """
        try:
            self.GET('/api/v1/Configuration/ServerName/$value', '')
            return True
        except:
            return False

    def set_version(self):
        request = '/api/v1/Configuration/ProductVersion/$value'
        response = self.GET(url=request)
        self._version = response.text

    @property
    def version(self):
        return self._version

    @property
    def session_id(self):
        return self._s.cookies["TM1SessionId"]

    @staticmethod
    def translate_to_boolean(value):
        """ Takes a boolean or string (eg. true, True, FALSE, etc.) value and returns (boolean) True or False
        :param value: True, 'true', 'false' or 'False' ...
        :return:
        """
        if isinstance(value, bool) or isinstance(value, int):
            return value
        elif isinstance(value, str):
            return value.lower() == 'true'
        else:
            raise ValueError("Invalid argument: " + value + ". Needs to be of type boolean or string")

    @staticmethod
    def b64_decode_password(encrypted_password):
        """ b64 decoding
        :param encrypted_password: encrypted password with b64
        :return: password in plain text
        """
        return b64decode(encrypted_password).decode("UTF-8")

    @staticmethod
    def verify_response(response):
        """ check if Status Code is OK
        :Parameters:
            `response`: String
                the response that is returned from a method call
        :Exceptions:
            TM1pyException, raises TM1pyException when Code is not 200, 204 etc.
        """
        if not response.ok:
            raise TM1pyException(response.text,
                                 status_code=response.status_code,
                                 reason=response.reason,
                                 headers=response.headers)

    @staticmethod
    def _build_authorization_token(user, password, namespace=None, gateway=None, verify=False, **kwargs):
        """ Build the Authorization Header for CAM and Native Security
        """
        if namespace:
            return RestService._build_authorization_token_cam(user, password, namespace, gateway, verify)
        else:
            return RestService._build_authorization_token_basic(user, password)

    @staticmethod
    def _build_authorization_token_cam(user=None, password=None, namespace=None, gateway=None, verify=False):
        if gateway:
            try:
                HttpNegotiateAuth
            except NameError:
                raise RuntimeError(
                    "SSO failed due to missing dependency requests_negotiate_sspi.HttpNegotiateAuth. "
                    "SSO only supported for Windows")
            response = requests.get(gateway, auth=HttpNegotiateAuth(), verify=verify,
                                    params={"CAMNamespace": namespace})
            if not response.status_code == 200:
                raise RuntimeError(
                    "Failed to authenticate through CAM. Expected status_code 200, received status_code: "
                    + str(response.status_code))
            elif 'cam_passport' not in response.cookies:
                raise RuntimeError(
                    "Failed to authenticate through CAM. HTTP response does not contain 'cam_passport' cookie")
            else:
                return 'CAMPassport ' + response.cookies['cam_passport']
        else:
            return 'CAMNamespace ' + b64encode(str.encode("{}:{}:{}".format(user, password, namespace))).decode("ascii")

    @staticmethod
    def _build_authorization_token_basic(user, password):
        return 'Basic ' + b64encode(str.encode("{}:{}".format(user, password))).decode("ascii")

    @staticmethod
    def disable_http_warnings():
        # disable HTTP verification warnings from requests library
        requests.packages.urllib3.disable_warnings()

    def get_http_header(self, key):
        return self._headers[key]

    def add_http_header(self, key, value):
        self._headers[key] = value

    def remove_http_header(self, key):
        if key in self._headers:
            self._headers.pop(key)
