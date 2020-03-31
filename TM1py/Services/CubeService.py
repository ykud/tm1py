# -*- coding: utf-8 -*-
import json
import random

from TM1py.Objects.Cube import Cube
from TM1py.Services.CellService import CellService
from TM1py.Services.ObjectService import ObjectService
from TM1py.Services.ViewService import ViewService
from TM1py.Utils import format_url


class CubeService(ObjectService):
    """ Service to handle Object Updates for TM1 Cubes

    """

    def __init__(self, rest):
        # to avoid Circular dependency of modules
        from TM1py.Services.AnnotationService import AnnotationService
        super().__init__(rest)
        self.cells = CellService(rest)
        self.views = ViewService(rest)
        self.annotations = AnnotationService(rest)

    def create(self, cube):
        """ create new cube on TM1 Server

        :param cube: instance of TM1py.Cube
        :return: response
        """
        request = "/api/v1/Cubes"
        return self._rest.POST(request, cube.body)

    def get(self, cube_name):
        """ get cube from TM1 Server

        :param cube_name:
        :return: instance of TM1py.Cube
        """
        request = "/api/v1/Cubes('{}')?$expand=Dimensions($select=Name)".format(cube_name)
        response = self._rest.GET(request)
        cube = Cube.from_json(response.text)
        return cube

    def get_last_data_update(self, cube_name):
        request = "/api/v1/Cubes('{}')/LastDataUpdate/$value".format(cube_name)
        return self._rest.GET(request)

    def get_all(self):
        """ get all cubes from TM1 Server as TM1py.Cube instances

        :return: List of TM1py.Cube instances
        """
        request = "/api/v1/Cubes?$expand=Dimensions($select=Name)"
        response = self._rest.GET(request)
        cubes = [Cube.from_dict(cube_as_dict=cube) for cube in response.json()['value']]
        return cubes

    def get_model_cubes(self):
        """ Get all Cubes without } prefix from TM1 Server as TM1py.Cube instances

        :return: List of TM1py.Cube instances
        """
        request = "/api/v1/ModelCubes()?$expand=Dimensions($select=Name)"
        response = self._rest.GET(request)
        cubes = [Cube.from_dict(cube_as_dict=cube) for cube in response.json()['value']]
        return cubes

    def get_control_cubes(self):
        """ Get all Cubes with } prefix from TM1 Server as TM1py.Cube instances

        :return: List of TM1py.Cube instances
        """
        request = "/api/v1/ControlCubes()?$expand=Dimensions($select=Name)"
        response = self._rest.GET(request)
        cubes = [Cube.from_dict(cube_as_dict=cube) for cube in response.json()['value']]
        return cubes

    def update(self, cube):
        """ Update existing cube on TM1 Server

        :param cube: instance of TM1py.Cube
        :return: response
        """
        request = "/api/v1/Cubes('{}')".format(cube.name)
        return self._rest.PATCH(request, cube.body)

    def update_or_create(self, cube):
        """ update if exists else create

        :param cube:
        :return:
        """
        if self.exists(cube_name=cube.name):
            return self.update(cube=cube)
        else:
            return self.create(cube=cube)

    def check_rules(self, cube_name):
        """ Check rules syntax for existing cube on TM1 Server

        :param cube_name: name of a cube
        :return: response
        """
        request = "/api/v1/Cubes('{}')/tm1.CheckRules".format(cube_name)
        return self._rest.POST(request)

    def delete(self, cube_name):
        """ Delete a cube in TM1

        :param cube_name:
        :return: response
        """
        request = "/api/v1/Cubes('{}')".format(cube_name)
        return self._rest.DELETE(request)

    def exists(self, cube_name):
        """ Check if a cube exists. Return boolean.

        :param cube_name: 
        :return: Boolean 
        """
        request = "/api/v1/Cubes('{}')".format(cube_name)
        return self._exists(request)

    def get_all_names(self):
        """ Ask TM1 Server for list of all cube names

        :return: List of Strings
        """
        response = self._rest.GET('/api/v1/Cubes?$select=Name', '')
        list_cubes = list(entry['Name'] for entry in response.json()['value'])
        return list_cubes

    def get_dimension_names(self, cube_name, skip_sandbox_dimension=True, **kwargs):
        """ get name of the dimensions of a cube in their correct order

        :param cube_name:
        :param skip_sandbox_dimension:
        :return:  List : [dim1, dim2, dim3, etc.]
        """
        request = format_url("/api/v1/Cubes('{}')/Dimensions?$select=Name", cube_name)
        response = self._rest.GET(request, **kwargs)
        dimension_names = [element['Name'] for element in response.json()['value']]
        if skip_sandbox_dimension and dimension_names[0] == CellService.SANDBOX_DIMENSION:
            return dimension_names[1:]
        return dimension_names

    def get_storage_dimension_order(self, cube_name):
        """ Get the storage dimension order of a cube

        :param cube_name:
        :return: List of dimension names
        """
        url = "/api/v1/Cubes('{}')/tm1.DimensionsStorageOrder()?$select=Name".format(cube_name)
        response = self._rest.GET(url)
        return [dimension["Name"] for dimension in response.json()["value"]]

    def update_storage_dimension_order(self, cube_name, dimension_names):
        """ Update the storage dimension order of a cube

        :param cube_name:
        :param dimension_names:
        :return:
        """
        url = "/api/v1/Cubes('{}')/tm1.ReorderDimensions".format(cube_name)
        payload = dict()
        payload['Dimensions@odata.bind'] = ["Dimensions('{}')".format(dimension)
                                            for dimension
                                            in dimension_names]
        return self._rest.POST(url=url, data=json.dumps(payload))

    def load(self, cube_name):
        """ Load the cube into memory on the server

        :param cube_name:
        :return:
        """
        url = "/api/v1/Cubes('{}')/tm1.Load".format(cube_name)
        return self._rest.POST(url=url)

    def unload(self, cube_name):
        """ Unload the cube from memory

        :param cube_name:
        :return:
        """
        url = "/api/v1/Cubes('{}')/tm1.Unload".format(cube_name)
        return self._rest.POST(url=url)

    def get_random_intersection(self, cube_name, unique_names=False):
        """ Get a random Intersection in a cube
        used mostly for regression testing.
        Not optimized, in terms of performance. Function Loads ALL elements for EACH dim...

        :param cube_name: 
        :param unique_names: unique names instead of plain element names 
        :return: List of elements
        """
        from TM1py.Services import DimensionService
        dimension_service = DimensionService(self._rest)
        dimensions = self.get_dimension_names(cube_name)
        elements = []
        for dimension in dimensions:
            hierarchy = dimension_service.get(dimension).default_hierarchy
            element = random.choice(list((hierarchy.elements.keys())))
            if unique_names:
                element = '[{}].[{}]'.format(dimension, element)
            elements.append(element)
        return elements
