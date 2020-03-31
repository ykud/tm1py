# -*- coding: utf-8 -*-

import json

from TM1py.Objects.User import User
from TM1py.Services.ObjectService import ObjectService
from TM1py.Utils.Utils import format_url


class SecurityService(ObjectService):
    """ Service to handle Security stuff
    
    """

    def __init__(self, rest):
        super().__init__(rest)

    def determine_actual_user_name(self, user_name):
        return self.determine_actual_object_name(object_class="Users", object_name=user_name)

    def determine_actual_group_name(self, group_name):
        return self.determine_actual_object_name(object_class="Groups", object_name=group_name)

    def create_user(self, user):
        """ Create a user on TM1 Server

        :param user: instance of TM1py.User
        :return: response
        """
        url = '/api/v1/Users'
        return self._rest.POST(url, user.body)

    def create_group(self, group_name):
        """ Create a Security group in the TM1 Server

        :param group_name:
        :return:
        """
        url = '/api/v1/Groups'
        return self._rest.POST(url, json.dumps({"Name": group_name}))

    def get_user(self, user_name):
        """ Get user from TM1 Server

        :param user_name:
        :return: instance of TM1py.User
        """
        user_name = self.determine_actual_user_name(user_name)
        url = format_url("/api/v1/Users('{}')?$expand=Groups", user_name)
        response = self._rest.GET(url)
        return User.from_dict(response.json())

    def get_current_user(self):
        """ Get user and group assignments of this session

        :return: instance of TM1py.User
        """
        url = "/api/v1/ActiveUser?$expand=Groups"
        response = self._rest.GET(url)
        return User.from_dict(response.json())

    def update_user(self, user):
        """ Update user on TM1 Server

        :param user: instance of TM1py.User
        :return: response
        """
        user.name = self.determine_actual_user_name(user.name)
        for current_group in self.get_groups(user.name):
            if current_group not in user.groups:
                self.remove_user_from_group(current_group, user.name)
        url = format_url("/api/v1/Users('{}')", user.name)
        return self._rest.PATCH(url, user.body)

    def delete_user(self, user_name):
        """ Delete user on TM1 Server

        :param user_name:
        :return: response
        """
        user_name = self.determine_actual_user_name(user_name)
        url = format_url("/api/v1/Users('{}')", user_name)
        return self._rest.DELETE(url)

    def delete_group(self, group_name):
        """ Delete a group in the TM1 Server

        :param group_name:
        :return:
        """
        group_name = self.determine_actual_group_name(group_name)
        url = format_url("/api/v1/Groups('{}')", group_name)
        return self._rest.DELETE(url)

    def get_all_users(self):
        """ Get all users from TM1 Server

        :return: List of TM1py.User instances
        """
        url = '/api/v1/Users?$expand=Groups'
        response = self._rest.GET(url)
        users = [User.from_dict(user) for user in response.json()['value']]
        return users

    def get_all_user_names(self):
        """ Get all user names from TM1 Server

        :return: List of TM1py.User instances
        """
        url = '/api/v1/Users?select=Name'
        response = self._rest.GET(url)
        users = [user["Name"] for user in response.json()['value']]
        return users

    def get_users_from_group(self, group_name):
        """ Get all users from group

        :param group_name:
        :return: List of TM1py.User instances
        """
        url = format_url("/api/v1/Groups('{}')?$expand=Users($expand=Groups)", group_name)
        response = self._rest.GET(url)
        users = [User.from_dict(user) for user in response.json()['Users']]
        return users

    def get_user_names_from_group(self, group_name):
        """ Get all users from group

        :param group_name:
        :return: List of strings
        """
        url = format_url("/api/v1/Groups('{}')?$expand=Users($expand=Groups)", group_name)
        response = self._rest.GET(url)
        users = [user["Name"] for user in response.json()['Users']]
        return users

    def get_groups(self, user_name):
        """ Get the groups of a user in TM1 Server

        :param user_name:
        :return: List of strings
        """
        user_name = self.determine_actual_user_name(user_name)
        url = format_url("/api/v1/Users('{}')/Groups", user_name)
        response = self._rest.GET(url)
        return [group['Name'] for group in response.json()['value']]

    def add_user_to_groups(self, user_name, groups):
        """
        
        :param user_name: name of user
        :param groups: iterable of groups
        :return: response
        """
        user_name = self.determine_actual_user_name(user_name)
        url = format_url("/api/v1/Users('{}')", user_name)
        body = {
            "Name": user_name,
            "Groups@odata.bind": [
                format_url("Groups('{}')", self.determine_actual_group_name(group))
                for group
                in groups]
        }
        return self._rest.PATCH(url, json.dumps(body))

    def remove_user_from_group(self, group_name, user_name):
        """ Remove user from group in TM1 Server

        :param group_name:
        :param user_name:
        :return: response
        """
        user_name = self.determine_actual_user_name(user_name)
        group_name = self.determine_actual_group_name(group_name)
        url = format_url("/api/v1/Users('{}')/Groups?$id=Groups('{}')", user_name, group_name)
        return self._rest.DELETE(url)

    def get_all_groups(self):
        """ Get all groups from TM1 Server

        :return: List of strings
        """
        url = '/api/v1/Groups?$select=Name'
        response = self._rest.GET(url)
        groups = [entry['Name'] for entry in response.json()['value']]
        return groups

    def security_refresh(self):
        from TM1py.Services import ProcessService
        ti = "SecurityRefresh;"
        process_service = ProcessService(self._rest)
        return process_service.execute_ti_code(ti)
