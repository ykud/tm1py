# -*- coding: utf-8 -*-

import functools
import json
import warnings
from collections import OrderedDict
from io import StringIO
from typing import List, Union, Dict, Iterable

import pandas as pd
from requests import Response

from TM1py.Services.ObjectService import ObjectService
from TM1py.Services.RestService import RestService
from TM1py.Utils import Utils, CaseAndSpaceInsensitiveSet, format_url
from TM1py.Utils.Utils import build_pandas_dataframe_from_cellset, dimension_name_from_element_unique_name, \
    CaseAndSpaceInsensitiveTuplesDict


def tidy_cellset(func):
    """ Higher Order Function to tidy up cellset after usage
    """

    @functools.wraps(func)
    def wrapper(self, cellset_id, *args, **kwargs):
        try:
            return func(self, cellset_id, *args, **kwargs)
        finally:
            if kwargs.get("delete_cellset", True):
                self.delete_cellset(cellset_id=cellset_id)

    return wrapper


class CellService(ObjectService):
    """ Service to handle Read and Write operations to TM1 cubes
    
    """

    def __init__(self, tm1_rest: RestService):
        """
        
        :param tm1_rest: instance of RestService
        """
        super().__init__(tm1_rest)

    def get_value(self, cube_name: str, element_string: str, dimensions: List[str] = None,
                  **kwargs) -> Union[str, float]:
        """ Element_String describes the Dimension-Hierarchy-Element arrangement
            
        :param cube_name: Name of the cube
        :param element_string: "Hierarchy1::Element1 && Hierarchy2::Element4, Element9, Element2"
            - Dimensions are not specified! They are derived from the position.
            - The , seperates the element-selections
            - If more than one hierarchy is selected per dimension && splits the elementselections
            - If no Hierarchy is specified. Default Hierarchy will be addressed
        :param dimensions: List of dimension names in correct order
        :return: 
        """
        mdx_template = "SELECT {} ON ROWS, {} ON COLUMNS FROM [{}]"
        mdx_rows_list = []
        from TM1py.Services.CubeService import CubeService
        if not dimensions:
            dimensions = CubeService(self._rest).get(cube_name).dimensions
        element_selections = element_string.split(',')
        # Build the ON ROWS statement:
        # Loop through the comma seperated element selection, except for the last one
        for dimension_name, element_selection in zip(dimensions[:-1], element_selections[:-1]):
            if "&&" not in element_selection:
                mdx_rows_list.append("{[" + dimension_name + "].[" + dimension_name + "].[" + element_selection + "]}")
            else:
                for element_selection_part in element_selection.split('&&'):
                    hierarchy_name, element_name = element_selection_part.split('::')
                    mdx_rows_list.append("{[" + dimension_name + "].[" + hierarchy_name + "].[" + element_name + "]}")
        mdx_rows = "*".join(mdx_rows_list)
        # Build the ON COLUMNS statement from last dimension
        mdx_columns = ""
        if "&&" not in element_selections[-1]:
            mdx_columns = "{[" + dimensions[-1] + "].[" + dimensions[-1] + "].[" + element_selections[-1] + "]}"
        else:
            mdx_columns_list = []
            for element_selection_part in element_selections[-1].split('&&'):
                hierarchy_name, element_name = element_selection_part.split('::')
                mdx_columns_list.append("{[" + dimensions[-1] + "].[" + hierarchy_name + "].[" + element_name + "]}")
                mdx_columns = "*".join(mdx_columns_list)
        # Construct final MDX
        mdx = mdx_template.format(mdx_rows, mdx_columns, cube_name)
        # Execute MDX
        cellset = dict(self.execute_mdx(mdx, **kwargs))
        return next(iter(cellset.values()))["Value"]

    def relative_proportional_spread(
            self,
            value: float,
            cube: str,
            unique_element_names: List[str],
            reference_unique_element_names: List[str],
            reference_cube: str = None,
            **kwargs) -> Response:
        """ Execute relative proportional spread

        :param value: value to be spread
        :param cube: name of the cube
        :param unique_element_names: target cell coordinates as unique element names (e.g. ["[d1].[c1]","[d2].[e3]"])
        :param reference_cube: name of the reference cube. Can be None
        :param reference_unique_element_names: reference cell coordinates as unique element names
        :return:
        """
        mdx = """
        SELECT
        {{ {rows} }} ON 0
        FROM [{cube}]
        """.format(rows="}*{".join(unique_element_names), cube=cube)
        cellset_id = self.create_cellset(mdx=mdx, **kwargs)

        payload = {
            "BeginOrdinal": 0,
            "Value": "RP" + str(value),
            "ReferenceCell@odata.bind": list(),
            "ReferenceCube@odata.bind":
                format_url("Cubes('{}')", reference_cube if reference_cube else cube)}
        for unique_element_name in reference_unique_element_names:
            payload["ReferenceCell@odata.bind"].append(
                format_url(
                    "Dimensions('{}')/Hierarchies('{}')/Elements('{}')",
                    *Utils.dimension_hierarchy_element_tuple_from_unique_name(unique_element_name)))

        return self._post_against_cellset(cellset_id=cellset_id, payload=payload, delete_cellset=True, **kwargs)

    def clear_spread(
            self,
            cube: str,
            unique_element_names: List[str],
            **kwargs) -> Response:
        """ Execute clear spread
        :param cube: name of the cube
        :param unique_element_names: target cell coordinates as unique element names (e.g. ["[d1].[c1]","[d2].[e3]"])
        :return:
        """
        mdx = """
        SELECT
        {{ {rows} }} ON 0
        FROM [{cube}]
        """.format(rows="}*{".join(unique_element_names), cube=cube)
        cellset_id = self.create_cellset(mdx=mdx, **kwargs)

        payload = {
            "BeginOrdinal": 0,
            "Value": "C",
            "ReferenceCell@odata.bind": list()}
        for unique_element_name in unique_element_names:
            payload["ReferenceCell@odata.bind"].append(
                format_url(
                    "Dimensions('{}')/Hierarchies('{}')/Elements('{}')",
                    *Utils.dimension_hierarchy_element_tuple_from_unique_name(unique_element_name)))

        return self._post_against_cellset(cellset_id=cellset_id, payload=payload, delete_cellset=True, **kwargs)

    @tidy_cellset
    def _post_against_cellset(self, cellset_id: str, payload: Dict, **kwargs) -> Response:
        url = format_url("/api/v1/Cellsets('{}')/tm1.Update", cellset_id)
        return self._rest.POST(url=url, data=json.dumps(payload), **kwargs)

    def get_dimension_names_for_writing(self, cube_name: str, **kwargs) -> List[str]:
        from TM1py.Services import CubeService
        cube_service = CubeService(self._rest)
        dimensions = cube_service.get_dimension_names(cube_name, True, **kwargs)
        return dimensions

    def write_value(self, value: Union[str, float], cube_name: str, element_tuple: Iterable,
                    dimensions: List[str] = None, **kwargs) -> Response:
        """ Write value into cube at specified coordinates

        :param value: the actual value
        :param cube_name: name of the target cube
        :param element_tuple: target coordinates
        :param dimensions: optional. Dimension names in their natural order. Will speed up the execution!
        :return: response
        """
        if not dimensions:
            dimensions = self.get_dimension_names_for_writing(cube_name=cube_name)
        url = format_url("/api/v1/Cubes('{}')/tm1.Update", cube_name)
        body_as_dict = OrderedDict()
        body_as_dict["Cells"] = [{}]
        body_as_dict["Cells"][0]["Tuple@odata.bind"] = [
            format_url("Dimensions('{}')/Hierarchies('{}')/Elements('{}')", dim, dim, elem)
            for dim, elem
            in zip(dimensions, element_tuple)]
        body_as_dict["Value"] = str(value) if value else ""
        data = json.dumps(body_as_dict, ensure_ascii=False)
        return self._rest.POST(url=url, data=data, **kwargs)

    def write_values(self, cube_name: str, cellset_as_dict: Dict, dimensions: List[str] = None, **kwargs) -> Response:
        """ Write values in cube.  
        For cellsets with > 1000 cells look into "write_values_through_cellset"

        :param cube_name: name of the cube
        :param cellset_as_dict: {(elem_a, elem_b, elem_c): 243, (elem_d, elem_e, elem_f) : 109}
        :param dimensions: optional. Dimension names in their natural order. Will speed up the execution!
        :return: Response
        """
        if not dimensions:
            dimensions = self.get_dimension_names_for_writing(cube_name=cube_name)
        url = format_url("/api/v1/Cubes('{}')/tm1.Update", cube_name)
        updates = []
        for element_tuple, value in cellset_as_dict.items():
            body_as_dict = OrderedDict()
            body_as_dict["Cells"] = [{}]
            body_as_dict["Cells"][0]["Tuple@odata.bind"] = [
                format_url(
                    "Dimensions('{}')/Hierarchies('{}')/Elements('{}')",
                    dim, dim, elem)
                for dim, elem
                in zip(dimensions, element_tuple)]
            body_as_dict["Value"] = str(value) if value else ""
            updates.append(json.dumps(body_as_dict, ensure_ascii=False))
        updates = '[' + ','.join(updates) + ']'
        return self._rest.POST(url=url, data=updates, **kwargs)

    def write_values_through_cellset(self, mdx: str, values: List, **kwargs) -> Response:
        """ Significantly faster than write_values function
        Cellset gets created according to MDX Expression. For instance:
        [[61, 29 ,13], 
        [42, 54, 15], 
        [17, 28, 81]]
        
        Each value in the cellset can be addressed through its position: The ordinal integer value. 
        Ordinal-enumeration goes from top to bottom from left to right
        Number 61 has Ordinal 0, 29 has Ordinal 1, etc.

        The order of the iterable determines the insertion point in the cellset. 
        For instance:
        [91, 85, 72, 68, 51, 42, 35, 28, 11]

        would lead to:
        [[91, 85 ,72], 
        [68, 51, 42], 
        [35, 28, 11]]

        When writing large datasets into TM1 Cubes it can be convenient to call this function asynchronously.
        
        :param mdx: Valid MDX Expression.
        :param values: List of values. The Order of the List/ Iterable determines the insertion point in the cellset.
        :return: 
        """
        cellset_id = self.create_cellset(mdx, **kwargs)
        return self.update_cellset(cellset_id=cellset_id, values=values, **kwargs)

    @tidy_cellset
    def update_cellset(self, cellset_id: str, values: List, **kwargs) -> Response:
        """ Write values into cellset

        Number of values must match the number of cells in the cellset

        :param cellset_id: 
        :param values: iterable with Numeric and String values
        :return: 
        """
        request = format_url("/api/v1/Cellsets('{}')/Cells", cellset_id)
        data = []
        for o, value in enumerate(values):
            data.append({
                "Ordinal": o,
                "Value": value
            })
        return self._rest.PATCH(request, json.dumps(data, ensure_ascii=False), **kwargs)

    def execute_mdx(self, mdx: str, cell_properties: List[str] = None, top: int = None,
                    skip_contexts: bool = False, **kwargs) -> CaseAndSpaceInsensitiveTuplesDict:
        """ Execute MDX and return the cells with their properties

        :param mdx: MDX Query, as string
        :param cell_properties: properties to be queried from the cell. E.g. Value, Ordinal, RuleDerived, ... 
        :param top: integer
        :param skip_contexts: skip elements from titles / contexts in response
        :return: content in sweet concise structure.
        """
        cellset_id = self.create_cellset(mdx=mdx, **kwargs)
        return self.extract_cellset(
            cellset_id=cellset_id,
            cell_properties=cell_properties,
            top=top,
            skip_contexts=skip_contexts,
            delete_cellset=True,
            **kwargs)

    def execute_view(self, cube_name: str, view_name: str, cell_properties: List[str] = None, private: bool = False,
                     top: int = None, skip_contexts: bool = False,
                     **kwargs) -> CaseAndSpaceInsensitiveTuplesDict:
        """ get view content as dictionary with sweet and concise structure.
            Works on NativeView and MDXView !

        :param cube_name: String
        :param view_name: String
        :param cell_properties: List, cell properties: [Values, Status, HasPicklist, etc.]
        :param private: Boolean
        :param top: Int, number of cells to return (counting from top)
        :param skip_contexts: skip elements from titles / contexts in response

        :return: Dictionary : {([dim1].[elem1], [dim2][elem6]): {'Value':3127.312, 'Ordinal':12}   ....  }
        """
        cellset_id = self.create_cellset_from_view(cube_name=cube_name, view_name=view_name, private=private, **kwargs)
        return self.extract_cellset(
            cellset_id=cellset_id,
            cell_properties=cell_properties,
            top=top,
            skip_contexts=skip_contexts,
            delete_cellset=True,
            **kwargs)

    def execute_mdx_raw(
            self,
            mdx: str,
            cell_properties: List[str] = None,
            elem_properties: List[str] = None,
            member_properties: List[str] = None,
            top: int = None,
            skip_contexts: bool = False,
            **kwargs) -> Dict:
        """ Execute MDX and return the raw data from TM1

        :param mdx: String, a valid MDX Query
        :param cell_properties: List of properties to be queried from the cell. E.g. ['Value', 'RuleDerived', ...]
        :param elem_properties: List of properties to be queried from the elements. E.g. ['Name','Attributes', ...]
        :param member_properties: List of properties to be queried from the members. E.g. ['Name','Attributes', ...]
        :param top: Integer limiting the number of cells and the number or rows returned
        :param skip_contexts: skip elements from titles / contexts in response
        :return: Raw format from TM1.
        """
        cellset_id = self.create_cellset(mdx=mdx, **kwargs)
        return self.extract_cellset_raw(
            cellset_id=cellset_id,
            cell_properties=cell_properties,
            elem_properties=elem_properties,
            member_properties=member_properties,
            top=top,
            delete_cellset=True,
            skip_contexts=skip_contexts,
            **kwargs)

    def execute_view_raw(
            self,
            cube_name: str,
            view_name: str,
            private: bool = False,
            cell_properties: List[str] = None,
            elem_properties: List[str] = None,
            member_properties: List[str] = None,
            top: int = None,
            skip_contexts: bool = False,
            **kwargs) -> Dict:
        """ Execute a cube view and return the raw data from TM1

        :param cube_name: String, name of the cube
        :param view_name: String, name of the view
        :param private: True (private) or False (public)
        :param cell_properties: List of properties to be queried from the cell. E.g. ['Value', 'RuleDerived', ...]
        :param elem_properties: List of properties to be queried from the elements. E.g. ['Name','Attributes', ...]
        :param member_properties: List of properties to be queried from the members. E.g. ['Name','Attributes', ...]
        :param top: Integer limiting the number of cells and the number or rows returned
        :param skip_contexts: skip elements from titles / contexts in response
        :return: Raw format from TM1.
        """
        cellset_id = self.create_cellset_from_view(cube_name=cube_name, view_name=view_name, private=private, **kwargs)
        return self.extract_cellset_raw(
            cellset_id=cellset_id,
            cell_properties=cell_properties,
            elem_properties=elem_properties,
            member_properties=member_properties,
            top=top,
            skip_contexts=skip_contexts,
            delete_cellset=True,
            **kwargs)

    def execute_mdx_values(self, mdx: str, **kwargs):
        """ Optimized for performance. Query only raw cell values. 
        Coordinates are omitted !

        :param mdx: a valid MDX Query
        :return: Generator of cell values
        """
        cellset_id = self.create_cellset(mdx=mdx, **kwargs)
        return self.extract_cellset_values(cellset_id, delete_cellset=True, **kwargs)

    def execute_view_values(self, cube_name: str, view_name: str, private: bool = False, **kwargs):
        cellset_id = self.create_cellset_from_view(cube_name=cube_name, view_name=view_name, private=private, **kwargs)
        return self.extract_cellset_values(cellset_id, delete_cellset=True, **kwargs)

    def execute_mdx_rows_and_values(self, mdx: str, element_unique_names: bool = True,
                                    **kwargs) -> CaseAndSpaceInsensitiveTuplesDict:
        cellset_id = self.create_cellset(mdx=mdx, **kwargs)
        return self.extract_cellset_rows_and_values(cellset_id, element_unique_names, delete_cellset=True, **kwargs)

    def execute_view_rows_and_values(self, cube_name: str, view_name: str, private: bool = False,
                                     element_unique_names: bool = True, **kwargs) -> CaseAndSpaceInsensitiveTuplesDict:
        cellset_id = self.create_cellset_from_view(cube_name=cube_name, view_name=view_name, private=private, **kwargs)
        return self.extract_cellset_rows_and_values(cellset_id, element_unique_names, delete_cellset=True, **kwargs)

    def execute_mdx_csv(self, mdx: str, **kwargs) -> str:
        """ Optimized for performance. Get csv string of coordinates and values. 
        Context dimensions are omitted !
        Cells with Zero/null are omitted !

        :param mdx: Valid MDX Query 
        :return: String
        """
        cellset_id = self.create_cellset(mdx, **kwargs)
        return self.extract_cellset_csv(cellset_id=cellset_id, delete_cellset=True, **kwargs)

    def execute_view_csv(self, cube_name: str, view_name: str, private: bool = False, **kwargs) -> str:
        cellset_id = self.create_cellset_from_view(cube_name=cube_name, view_name=view_name, private=private)
        return self.extract_cellset_csv(cellset_id=cellset_id, delete_cellset=True, **kwargs)

    def execute_mdx_dataframe(self, mdx: str, **kwargs) -> pd.DataFrame:
        """ Optimized for performance. Get Pandas DataFrame from MDX Query.

        Context dimensions are omitted in the resulting Dataframe !
        Cells with Zero/null are omitted !

        Takes all arguments from the pandas.read_csv method:
        https://pandas.pydata.org/pandas-docs/stable/reference/api/pandas.read_csv.html

        :param mdx: Valid MDX Query
        :return: Pandas Dataframe
        """
        cellset_id = self.create_cellset(mdx, **kwargs)
        return self.extract_cellset_dataframe(cellset_id, **kwargs)

    def execute_view_dataframe_pivot(self, cube_name: str, view_name: str, private: bool = False, dropna: bool = False,
                                     fill_value: bool = None, **kwargs) -> pd.DataFrame:
        """ Execute a cube view to get a pandas pivot dataframe, in the shape of the cube view

        :param cube_name:
        :param view_name:
        :param private:
        :param dropna:
        :param fill_value:
        :return:
        """
        cellset_id = self.create_cellset_from_view(cube_name=cube_name, view_name=view_name, private=private, **kwargs)
        return self.extract_cellset_dataframe_pivot(
            cellset_id=cellset_id,
            dropna=dropna,
            fill_value=fill_value,
            **kwargs)

    def execute_mdx_dataframe_pivot(self, mdx: str, dropna: bool = False, fill_value: bool = None) -> pd.DataFrame:
        """ Execute MDX Query to get a pandas pivot data frame in the shape as specified in the Query

        :param mdx:
        :param dropna:
        :param fill_value:
        :return:
        """
        cellset_id = self.create_cellset(mdx=mdx)
        return self.extract_cellset_dataframe_pivot(
            cellset_id=cellset_id,
            dropna=dropna,
            fill_value=fill_value)

    def execute_view_dataframe(self, cube_name: str, view_name: str, private: bool = False, **kwargs) -> pd.DataFrame:
        """ Optimized for performance. Get Pandas DataFrame from an existing Cube View 
        Context dimensions are omitted in the resulting Dataframe !
        Cells with Zero/null are omitted !

        Takes all arguments from the pandas.read_csv method:
        https://pandas.pydata.org/pandas-docs/stable/reference/api/pandas.read_csv.html

        :param cube_name: Name of the 
        :param view_name: 
        :param private: 
        :return: Pandas Dataframe
        """
        cellset_id = self.create_cellset_from_view(cube_name=cube_name, view_name=view_name, private=private, **kwargs)
        return self.extract_cellset_dataframe(cellset_id, **kwargs)

    def execute_mdx_cellcount(self, mdx: str, **kwargs) -> int:
        """ Execute MDX in order to understand how many cells are in a cellset.
        Only return number of cells in the cellset. FAST!

        :param mdx: MDX Query, as string
        :return: Number of Cells in the CellSet
        """
        cellset_id = self.create_cellset(mdx, **kwargs)
        return self.extract_cellset_cellcount(cellset_id, delete_cellset=True, **kwargs)

    def execute_view_cellcount(self, cube_name: str, view_name: str, private: bool = False, **kwargs) -> int:
        """ Execute cube view in order to understand how many cells are in a cellset.
        Only return number of cells in the cellset. FAST!
        
        :param cube_name: cube name
        :param view_name: view name
        :param private: True (private) or False (public)
        :return: 
        """
        cellset_id = self.create_cellset_from_view(cube_name=cube_name, view_name=view_name, private=private, **kwargs)
        return self.extract_cellset_cellcount(cellset_id, delete_cellset=True, **kwargs)

    def execute_mdx_rows_and_values_string_set(
            self,
            mdx: str,
            exclude_empty_cells: bool = True,
            **kwargs) -> CaseAndSpaceInsensitiveSet:
        """ Retrieve row element names and **string** cell values in a case and space insensitive set

        :param exclude_empty_cells:
        :param mdx:
        :return:
        """
        rows_and_values = self.execute_mdx_rows_and_values(mdx, element_unique_names=False, **kwargs)
        return self._extract_string_set_from_rows_and_values(rows_and_values, exclude_empty_cells)

    def execute_view_rows_and_values_string_set(self, cube_name: str, view_name: str, private: bool = False,
                                                exclude_empty_cells: bool = True,
                                                **kwargs) -> CaseAndSpaceInsensitiveSet:
        """ Retrieve row element names and **string** cell values in a case and space insensitive set

        :param cube_name:
        :param view_name:
        :param private:
        :param exclude_empty_cells:
        :return:
        """
        rows_and_values = self.execute_view_rows_and_values(cube_name, view_name, private, False, **kwargs)
        return self._extract_string_set_from_rows_and_values(rows_and_values, exclude_empty_cells)

    def execute_mdx_ui_dygraph(
            self,
            mdx: str,
            elem_properties: List[str] = None,
            member_properties: List[str] = None,
            value_precision: List[str] = 2,
            top: int = None,
            **kwargs) -> Dict:
        """ Execute MDX get dygraph dictionary
        Useful for grids or charting libraries that want an array of cell values per column
        Returns 3-dimensional cell structure for tabbed grids or multiple charts
        Example 'cells' return format:
            'cells': {
                '10100': [
                    ['Q1-2004', 28981046.50724231, 19832724.72429739],
                    ['Q2-2004', 29512482.207418434, 20365654.788303416],
                    ['Q3-2004', 29913730.038971487, 20729201.329183243],
                    ['Q4-2004', 29563345.9542385, 20480205.20121749]],
                '10200': [
                    ['Q1-2004', 13888143.710000003, 9853293.623709997],
                    ['Q2-2004', 14300216.43, 10277650.763958748],
                    ['Q3-2004', 14502421.63, 10466934.096533755],
                    ['Q4-2004', 14321501.940000001, 10333095.839474997]]
            },
        :param top:
        :param mdx: String, valid MDX Query
        :param elem_properties: List of properties to be queried from the elements. E.g. ['UniqueName','Attributes']
        :param member_properties: List of properties to be queried from the members. E.g. ['UniqueName','Attributes']
        :param value_precision: Integer (optional) specifying number of decimal places to return
        :return: dict: { titles: [], headers: [axis][], cells: { Page0: [ [column name, column values], [], ... ], ...}}
        """
        cellset_id = self.create_cellset(mdx)
        data = self.extract_cellset_raw(cellset_id=cellset_id,
                                        cell_properties=["Value"],
                                        elem_properties=elem_properties,
                                        member_properties=list(set(member_properties or []) | {"Name"}),
                                        top=top,
                                        delete_cellset=True,
                                        **kwargs)
        return Utils.build_ui_dygraph_arrays_from_cellset(raw_cellset_as_dict=data, value_precision=value_precision)

    def execute_view_ui_dygraph(
            self,
            cube_name: str,
            view_name: str,
            private: bool = False,
            elem_properties: List[str] = None,
            member_properties: List[str] = None,
            value_precision: int = 2,
            top: int = None,
            **kwargs):
        """
        Useful for grids or charting libraries that want an array of cell values per row.
        Returns 3-dimensional cell structure for tabbed grids or multiple charts.
        Rows and pages are dicts, addressable by their name. Proper order of rows can be obtained in headers[1]
        Example 'cells' return format:
            'cells': {
                '10100': {
                    'Net Operating Income': [ 19832724.72429739,
                                              20365654.788303416,
                                              20729201.329183243,
                                              20480205.20121749],
                    'Revenue': [ 28981046.50724231,
                                 29512482.207418434,
                                 29913730.038971487,
                                 29563345.9542385]},
                '10200': {
                    'Net Operating Income': [ 9853293.623709997,
                                               10277650.763958748,
                                               10466934.096533755,
                                               10333095.839474997],
                    'Revenue': [ 13888143.710000003,
                                 14300216.43,
                                 14502421.63,
                                 14321501.940000001]}
            },

        :param top:
        :param cube_name: cube name
        :param view_name: view name
        :param private: True (private) or False (public)
        :param elem_properties: List of properties to be queried from the elements. E.g. ['UniqueName','Attributes']
        :param member_properties: List of properties to be queried from the members. E.g. ['UniqueName','Attributes']
        :param value_precision: Integer (optional) specifying number of decimal places to return
        :return:
        """
        cellset_id = self.create_cellset_from_view(cube_name=cube_name, view_name=view_name, private=private, **kwargs)
        data = self.extract_cellset_raw(cellset_id=cellset_id,
                                        cell_properties=["Value"],
                                        elem_properties=elem_properties,
                                        member_properties=list(set(member_properties or []) | {"Name"}),
                                        top=top,
                                        delete_cellset=True,
                                        **kwargs)
        return Utils.build_ui_dygraph_arrays_from_cellset(raw_cellset_as_dict=data, value_precision=value_precision)

    def execute_mdx_ui_array(
            self,
            mdx: str,
            elem_properties: List[str] = None,
            member_properties: List[str] = None,
            value_precision: int = 2,
            top: int = None,
            **kwargs):
        """
        Useful for grids or charting libraries that want an array of cell values per row.
        Returns 3-dimensional cell structure for tabbed grids or multiple charts.
        Rows and pages are dicts, addressable by their name. Proper order of rows can be obtained in headers[1]
        Example 'cells' return format:
            'cells': {
                '10100': {
                    'Net Operating Income': [ 19832724.72429739,
                                              20365654.788303416,
                                              20729201.329183243,
                                              20480205.20121749],
                    'Revenue': [ 28981046.50724231,
                                 29512482.207418434,
                                 29913730.038971487,
                                 29563345.9542385]},
                '10200': {
                    'Net Operating Income': [ 9853293.623709997,
                                               10277650.763958748,
                                               10466934.096533755,
                                               10333095.839474997],
                    'Revenue': [ 13888143.710000003,
                                 14300216.43,
                                 14502421.63,
                                 14321501.940000001]}
            },

        :param top:
        :param mdx: a valid MDX Query
        :param elem_properties: List of properties to be queried from the elements. E.g. ['UniqueName','Attributes']
        :param member_properties: List of properties to be queried from the members. E.g. ['UniqueName','Attributes']
        :param value_precision: Integer (optional) specifying number of decimal places to return
        :return: dict :{ titles: [], headers: [axis][], cells:{ Page0:{ Row0:{ [row values], Row1: [], ...}, ...}, ...}}
        """
        cellset_id = self.create_cellset(mdx, **kwargs)
        data = self.extract_cellset_raw(cellset_id=cellset_id,
                                        cell_properties=["Value"],
                                        elem_properties=elem_properties,
                                        member_properties=list(set(member_properties or []) | {"Name"}),
                                        top=top,
                                        delete_cellset=True,
                                        **kwargs)
        return Utils.build_ui_arrays_from_cellset(raw_cellset_as_dict=data, value_precision=value_precision)

    def execute_view_ui_array(
            self,
            cube_name: str,
            view_name: str,
            private: bool = False,
            elem_properties: List[str] = None,
            member_properties: List[str] = None,
            value_precision: int = 2,
            top: int = None,
            **kwargs):
        """
        Useful for grids or charting libraries that want an array of cell values per row.
        Returns 3-dimensional cell structure for tabbed grids or multiple charts.
        Rows and pages are dicts, addressable by their name. Proper order of rows can be obtained in headers[1]
        Example 'cells' return format:
            'cells': {
                '10100': {
                    'Net Operating Income': [ 19832724.72429739,
                                              20365654.788303416,
                                              20729201.329183243,
                                              20480205.20121749],
                    'Revenue': [ 28981046.50724231,
                                 29512482.207418434,
                                 29913730.038971487,
                                 29563345.9542385]},
                '10200': {
                    'Net Operating Income': [ 9853293.623709997,
                                               10277650.763958748,
                                               10466934.096533755,
                                               10333095.839474997],
                    'Revenue': [ 13888143.710000003,
                                 14300216.43,
                                 14502421.63,
                                 14321501.940000001]}
            },

        :param top:
        :param cube_name: cube name
        :param view_name: view name
        :param private: True (private) or False (public)
        :param elem_properties: List of properties to be queried from the elements. E.g. ['UniqueName','Attributes']
        :param member_properties: List properties to be queried from the member. E.g. ['Name', 'UniqueName']
        :param value_precision: Integer (optional) specifying number of decimal places to return
        :return: dict :{ titles: [], headers: [axis][], cells:{ Page0:{ Row0: {[row values], Row1: [], ...}, ...}, ...}}
        """
        cellset_id = self.create_cellset_from_view(cube_name=cube_name, view_name=view_name, private=private, **kwargs)
        data = self.extract_cellset_raw(cellset_id=cellset_id,
                                        cell_properties=["Value"],
                                        elem_properties=elem_properties,
                                        member_properties=list(set(member_properties or []) | {"Name"}),
                                        top=top,
                                        delete_cellset=True,
                                        **kwargs)
        return Utils.build_ui_arrays_from_cellset(raw_cellset_as_dict=data, value_precision=value_precision)

    @tidy_cellset
    def extract_cellset_raw(
            self,
            cellset_id: str,
            cell_properties: List[str] = None,
            elem_properties: List[str] = None,
            member_properties: List[str] = None,
            top: int = None,
            skip_contexts: bool = False,
            **kwargs) -> Dict:
        """ Extract full Cellset data and return the raw data from TM1

        :param cellset_id: String; ID of existing cellset
        :param cell_properties: List of properties to be queried from cells. E.g. ['Value', 'RuleDerived', ...]
        :param elem_properties: List of properties to be queried from elements. E.g. ['UniqueName','Attributes', ...]
        :param member_properties: List properties to be queried from the member. E.g. ['Name', 'UniqueName']
        :param top: Integer limiting the number of cells and the number or rows returned
        :param skip_contexts:
        :return: Raw format from TM1.
        """
        if not cell_properties:
            cell_properties = ['Value']

        # select Name property if member_properties is None or empty.
        # Necessary, as tm1 default behaviour is to return all properties if no $select is specified in the request.
        if member_properties is None or len(member_properties) == 0:
            member_properties = ["Name"]
        select_member_properties = "$select={}".format(",".join(member_properties))

        expand_elem_properties = ";$expand=Element($select={elem_properties})".format(
            elem_properties=",".join(elem_properties)) \
            if elem_properties is not None and len(elem_properties) > 0 \
            else ""

        filter_axis = "$filter=Ordinal ne 2;" if skip_contexts else ""

        url = "/api/v1/Cellsets('{cellset_id}')?$expand=" \
              "Cube($select=Name;$expand=Dimensions($select=Name))," \
              "Axes({filter_axis}$expand=Tuples($expand=Members({select_member_properties}" \
              "{expand_elem_properties}){top_rows}))," \
              "Cells($select={cell_properties}{top_cells})" \
            .format(cellset_id=cellset_id,
                    top_rows=";$top={}".format(top) if top else "",
                    cell_properties=",".join(cell_properties),
                    filter_axis=filter_axis,
                    select_member_properties=select_member_properties,
                    expand_elem_properties=expand_elem_properties,
                    top_cells=";$top={}".format(top) if top else "")
        response = self._rest.GET(url=url, **kwargs)
        return response.json()

    @tidy_cellset
    def extract_cellset_values(self, cellset_id: str, **kwargs):
        """ Extract Cellset data and return only the cells and values

        :param cellset_id: String; ID of existing cellset
        :return: Raw format from TM1.
        """
        url = format_url("/api/v1/Cellsets('{}')?$expand=Cells($select=Value)", cellset_id)
        response = self._rest.GET(url=url, **kwargs)
        return (cell["Value"] for cell in response.json()["Cells"])

    @tidy_cellset
    def extract_cellset_rows_and_values(self, cellset_id: str, element_unique_names: bool = True,
                                        **kwargs) -> CaseAndSpaceInsensitiveTuplesDict:
        url = "/api/v1/Cellsets('{}')?$expand=" \
              "Axes($filter=Ordinal eq 1;$expand=Tuples(" \
              "$expand=Members($select=Element;$expand=Element($select={}))))," \
              "Cells($select=Value)".format(cellset_id, "UniqueName" if element_unique_names else "Name")
        response = self._rest.GET(url=url, **kwargs)
        response_json = response.json()
        rows = response_json["Axes"][0]["Tuples"]
        cell_values = [cell["Value"] for cell in response_json["Cells"]]

        result = CaseAndSpaceInsensitiveTuplesDict()

        number_rows = len(rows)
        # avoid division by zero
        if not number_rows:
            return result
        number_cells = len(cell_values)
        number_columns = int(number_cells / number_rows)

        cell_values_by_row = [cell_values[cell_counter:cell_counter + number_columns]
                              for cell_counter
                              in range(0, number_cells, number_columns)]
        element_names_by_row = [tuple(member["Element"]["UniqueName" if element_unique_names else "Name"]
                                      for member
                                      in tupl["Members"])
                                for tupl
                                in rows]
        for element_tuple, cells in zip(element_names_by_row, cell_values_by_row):
            result[element_tuple] = cells
        return result

    @tidy_cellset
    def extract_cellset_composition(self, cellset_id: str, **kwargs):
        url = "/api/v1/Cellsets('{}')?$expand=" \
              "Cube($select=Name)," \
              "Axes($expand=Hierarchies($select=UniqueName))".format(cellset_id)
        response = self._rest.GET(url=url, **kwargs)
        response_json = response.json()
        cube = response_json["Cube"]["Name"]

        rows, titles, columns = [], [], []
        if response_json["Axes"][0]["Hierarchies"]:
            columns = [hierarchy["UniqueName"] for hierarchy in response_json["Axes"][0]["Hierarchies"]]
        if response_json["Axes"][1]["Hierarchies"]:
            rows = [hierarchy["UniqueName"] for hierarchy in response_json["Axes"][1]["Hierarchies"]]
        if len(response_json["Axes"]) > 2:
            titles = [hierarchy["UniqueName"] for hierarchy in response_json["Axes"][2]["Hierarchies"]]
        return cube, titles, rows, columns

    @tidy_cellset
    def extract_cellset_cellcount(self, cellset_id: str, **kwargs) -> int:
        url = "/api/v1/Cellsets('{}')/Cells/$count".format(cellset_id)
        response = self._rest.GET(url, **kwargs)
        return int(response.content)

    @tidy_cellset
    def extract_cellset_csv(self, cellset_id: str, **kwargs) -> str:
        """ Execute Cellset and return only the 'Content', in csv format

        :param cellset_id: String; ID of existing cellset
        :return: Raw format from TM1.
        """
        url = "/api/v1/Cellsets('{}')/Content".format(cellset_id)
        data = self._rest.GET(url, **kwargs)
        return data.text

    def extract_cellset_dataframe(self, cellset_id: str, **kwargs) -> pd.DataFrame:
        """ Build pandas dataframe from cellset_id

        :param cellset_id:
        :param kwargs:
        :return:
        """
        raw_csv = self.extract_cellset_csv(cellset_id=cellset_id, delete_cellset=True, **kwargs)
        memory_file = StringIO(raw_csv)
        # make sure all element names are strings and values column is derived from data
        if 'dtype' not in kwargs:
            kwargs['dtype'] = {'Value': None, **{col: str for col in range(999)}}
        return pd.read_csv(memory_file, sep=',', **kwargs)

    @tidy_cellset
    def extract_cellset_power_bi(self, cellset_id: str, **kwargs) -> pd.DataFrame:
        url = "/api/v1/Cellsets('{}')?$expand=" \
              "Axes($filter=Ordinal eq 0 or Ordinal eq 1;$expand=Tuples(" \
              "$expand=Members($select=Name)),Hierarchies($select=Name))," \
              "Cells($select=Value)".format(cellset_id)
        response = self._rest.GET(url=url, **kwargs)
        response_json = response.json()
        rows = response_json["Axes"][1]["Tuples"]
        column_headers = [tupl["Members"][0]["Name"] for tupl in response_json["Axes"][0]["Tuples"]]
        row_headers = [hierarchy["Name"] for hierarchy in response_json["Axes"][1]["Hierarchies"]]
        cell_values = [cell["Value"] for cell in response_json["Cells"]]

        headers = row_headers + column_headers
        body = []

        number_rows = len(rows)
        # avoid division by zero
        if not number_rows:
            return pd.DataFrame(body, columns=headers)
        number_cells = len(cell_values)
        number_columns = int(number_cells / number_rows)

        cell_values_by_row = [cell_values[cell_counter:cell_counter + number_columns]
                              for cell_counter
                              in range(0, number_cells, number_columns)]
        element_names_by_row = [tuple(member["Name"]
                                      for member
                                      in tupl["Members"])
                                for tupl
                                in rows]

        for element_tuple, cells in zip(element_names_by_row, cell_values_by_row):
            body.append(list(element_tuple) + cells)
        return pd.DataFrame(body, columns=headers, dtype=str)

    def extract_cellset_dataframe_pivot(self, cellset_id: str, dropna: bool = False, fill_value: bool = False,
                                        **kwargs) -> pd.DataFrame:
        """ Extract a pivot table (pandas dataframe) from a cellset in TM1

        :param cellset_id:
        :param dropna:
        :param fill_value:
        :param kwargs:
        :return:
        """
        data = self.extract_cellset(
            cellset_id=cellset_id,
            delete_cellset=False,
            **kwargs)

        cube, titles, rows, columns = self.extract_cellset_composition(
            cellset_id=cellset_id,
            delete_cellset=True,
            **kwargs)

        df = build_pandas_dataframe_from_cellset(data, multiindex=False)
        return pd.pivot_table(
            data=df,
            index=[dimension_name_from_element_unique_name(hierarchy_unique_name) for hierarchy_unique_name in rows],
            columns=[dimension_name_from_element_unique_name(hierarchy_unique_name) for hierarchy_unique_name in
                     columns],
            values=["Values"],
            dropna=dropna,
            fill_value=fill_value,
            aggfunc='sum')

    def extract_cellset(
            self,
            cellset_id: str,
            cell_properties: List[str] = None,
            top: int = None,
            delete_cellset: bool = True,
            skip_contexts: bool = False,
            **kwargs) -> CaseAndSpaceInsensitiveTuplesDict:
        """ Execute cellset and return the cells with their properties

        :param skip_contexts:
        :param delete_cellset:
        :param cellset_id:
        :param cell_properties: properties to be queried from the cell. E.g. Value, Ordinal, RuleDerived, ...
        :param top: integer
        :return: Content in sweet consice strcuture.
        """
        if not cell_properties:
            cell_properties = ['Value']

        raw_cellset = self.extract_cellset_raw(
            cellset_id,
            cell_properties=cell_properties,
            elem_properties=['UniqueName'],
            member_properties=['UniqueName'],
            top=top,
            skip_contexts=skip_contexts,
            delete_cellset=delete_cellset,
            **kwargs)

        return Utils.build_content_from_cellset(
            raw_cellset_as_dict=raw_cellset,
            top=top)

    def create_cellset(self, mdx: str, **kwargs) -> str:
        """ Execute MDX in order to create cellset at server. return the cellset-id

        :param mdx: MDX Query, as string
        :return:
        """
        url = '/api/v1/ExecuteMDX'
        data = {
            'MDX': mdx
        }
        response = self._rest.POST(url=url, data=json.dumps(data, ensure_ascii=False), **kwargs)
        cellset_id = response.json()['ID']
        return cellset_id

    def create_cellset_from_view(self, cube_name: str, view_name: str, private: bool, **kwargs) -> str:
        url = "/api/v1/Cubes('{cube_name}')/{views}('{view_name}')/tm1.Execute".format(
            cube_name=cube_name,
            views='PrivateViews' if private else 'Views',
            view_name=view_name)
        return self._rest.POST(url=url, **kwargs).json()['ID']

    def delete_cellset(self, cellset_id: str, **kwargs) -> Response:
        """ Delete a cellset

        :param cellset_id:
        :return:
        """
        url = "/api/v1/Cellsets('{}')".format(cellset_id)
        return self._rest.DELETE(url, **kwargs)

    def deactivate_transactionlog(self, *args: str, **kwargs) -> Response:
        """ Deacctivate Transactionlog for one or many cubes

        :param args: one or many cube names
        :return:
        """
        updates = {}
        for cube_name in args:
            updates[(cube_name, "Logging")] = "NO"
        return self.write_values(cube_name="}CubeProperties", cellset_as_dict=updates, **kwargs)

    def activate_transactionlog(self, *args: str, **kwargs) -> Response:
        """ Activate Transactionlog for one or many cubes

        :param args: one or many cube names
        :return:
        """
        updates = {}
        for cube_name in args:
            updates[(cube_name, "Logging")] = "YES"
        return self.write_values(cube_name="}CubeProperties", cellset_as_dict=updates, **kwargs)

    def get_cellset_cells_count(self, mdx: str) -> int:
        """ Execute MDX in order to understand how many cells are in a cellset

        :param mdx: MDX Query, as string
        :return: Number of Cells in the CellSet
        """
        warnings.simplefilter('always', PendingDeprecationWarning)
        warnings.warn(
            "Function deprecated. Use execute_mdx_cellcount(self, mdx) instead.",
            PendingDeprecationWarning
        )
        warnings.simplefilter('default', PendingDeprecationWarning)
        return self.execute_mdx_cellcount(mdx)

    def get_view_content(self, cube_name: str, view_name: str, cell_properties: List[str] = None, private: bool = False,
                         top: int = None):
        warnings.simplefilter('always', PendingDeprecationWarning)
        warnings.warn(
            "Function deprecated. Use execute_view instead.",
            PendingDeprecationWarning
        )
        warnings.simplefilter('default', PendingDeprecationWarning)
        return self.execute_view(cube_name, view_name, cell_properties, private, top)

    @staticmethod
    def _extract_string_set_from_rows_and_values(
            rows_and_values: CaseAndSpaceInsensitiveTuplesDict,
            exclude_empty_cells: bool) -> CaseAndSpaceInsensitiveSet:
        """ Helper function for execute_..._string_set methods

        :param rows_and_values:
        :param exclude_empty_cells:
        :return:
        """
        result_set = CaseAndSpaceInsensitiveSet()
        for row_elements, cell_values in rows_and_values.items():
            for row_element in row_elements:
                result_set.add(row_element)
            for cell_value in cell_values:
                if isinstance(cell_value, str):
                    if cell_value or not exclude_empty_cells:
                        result_set.add(cell_value)
        return result_set
