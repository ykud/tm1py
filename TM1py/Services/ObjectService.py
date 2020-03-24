# -*- coding: utf-8 -*-

from TM1py.Exceptions import TM1pyException
from TM1py.Services import RestService
from TM1py.Utils import format_url


class ObjectService:
    """ Parent class for all Object Services
    
    """

    ELEMENT_ATTRIBUTES_PREFIX = "}ElementAttributes_"
    SANDBOX_DIMENSION = "Sandboxes"

    BINARY_HTTP_HEADER = {'Content-Type': 'application/octet-stream; odata.streaming=true'}

    def __init__(self, rest_service: RestService):
        """ Constructor, Create an instance of ObjectService
        
        :param rest_service: 
        """
        self._rest = rest_service

    def determine_actual_object_name(self, object_class, object_name):
        url = format_url(
            "/api/v1/{}?$filter=tolower(replace(Name, ' ', '')) eq '{}'",
            object_class,
            object_name.replace(" ", "").lower())
        response = self._rest.GET(url)

        if len(response.json()["value"]) == 0:
            raise ValueError("Object '{}' of type '{}' doesn't exist".format(object_name, object_class))

        return response.json()["value"][0]["Name"]

    def _exists(self, url: str) -> bool:
        """ Check if resource exists in the TM1 Server
        
        :param url: 
        :return: 
        """
        try:
            self._rest.GET(url)
            return True
        except TM1pyException as e:
            if e._status_code == 404:
                return False
            raise e

    @property
    def version(self):
        return self._rest.version
