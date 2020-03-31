# -*- coding: utf-8 -*-

import collections
import json

from TM1py.Objects.TM1Object import TM1Object
from TM1py.Utils.Utils import CaseAndSpaceInsensitiveSet, format_url


class User(TM1Object):
    """ Abstraction of a TM1 User
    
    """

    def __init__(self, name, groups, friendly_name=None, password=None):
        self._name = name
        self._groups = CaseAndSpaceInsensitiveSet(*groups)
        self._friendly_name = friendly_name
        self._password = password

    @property
    def name(self):
        return self._name

    @property
    def friendly_name(self):
        return self._friendly_name

    @property
    def password(self):
        if self._password:
            return self._password

    @property
    def is_admin(self):
        return 'ADMIN' in self.groups

    @property
    def groups(self):
        return [group for group in self._groups]

    @name.setter
    def name(self, value):
        self._name = value

    @friendly_name.setter
    def friendly_name(self, value):
        self._friendly_name = value

    @password.setter
    def password(self, value):
        self._password = value

    def add_group(self, group_name):
        self._groups.add(group_name)

    def remove_group(self, group_name):
        self._groups.discard(group_name)

    @classmethod
    def from_json(cls, user_as_json):
        """ Alternative constructor

        :param user_as_json: user as JSON string
        :return: user, an instance of this class
        """
        user_as_dict = json.loads(user_as_json)
        return cls.from_dict(user_as_dict)

    @classmethod
    def from_dict(cls, user_as_dict):
        """ Alternative constructor

        :param user_as_dict: user as dict
        :return: user, an instance of this class
        """
        return cls(name=user_as_dict['Name'],
                   friendly_name=user_as_dict['FriendlyName'],
                   groups=[group["Name"] for group in user_as_dict['Groups']])

    @property
    def body(self):
        return self.construct_body()

    def construct_body(self):
        """
        construct body (json) from the class attributes
        :return: String, TM1 JSON representation of a user
        """
        body_as_dict = collections.OrderedDict()
        body_as_dict['Name'] = self.name
        body_as_dict['FriendlyName'] = self.friendly_name or self.name
        if self.password:
            body_as_dict['Password'] = self._password
        body_as_dict['Groups@odata.bind'] = [format_url("Groups('{}')", group)
                                             for group
                                             in self.groups]
        return json.dumps(body_as_dict, ensure_ascii=False)
