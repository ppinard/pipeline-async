""""""

__all__ = ['Model', 'PassThroughModel', 'SqlModel']

# Standard library modules.
import abc
import datetime
import dataclasses
import inspect
import enum
import typing

# Third party modules.
import sqlalchemy
import sqlalchemy.sql
import pymongo
from loguru import logger

# Local modules.
from .datautil import iskeyfield, keyfields
from .util import camelcase_to_words

# Globals and constants variables.


class Model(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def exists(self, data):  # pragma: no cover
        raise NotImplementedError

    @abc.abstractmethod
    def add(self, data, check_exists=True):  # pragma: no cover
        raise NotImplementedError


class PassThroughModel(Model):
    def exists(self, data, check_exists=True):
        return False

    def add(self, data):
        return []

class _DatabaseModel(Model):

    def _get_table_name(self, data_or_dataclass):
        if not inspect.isclass(data_or_dataclass):
            data_or_dataclass = type(data_or_dataclass)

        name = data_or_dataclass.__name__.lower()
        return "_".join(camelcase_to_words(name).split())


class SqlModel(_DatabaseModel):

    TYPE_TO_SQLTYPE = {int: sqlalchemy.Integer, float: sqlalchemy.Float, str: sqlalchemy.String, bytes: sqlalchemy.LargeBinary, datetime.datetime: sqlalchemy.DateTime, datetime.date: sqlalchemy.Date, bool: sqlalchemy.Boolean}

    def __init__(self, engine):
        self.engine = engine

        self.metadata = sqlalchemy.MetaData()
        self.metadata.reflect(engine)

    @classmethod
    def from_filepath(cls, filepath):
        engine = sqlalchemy.create_engine("sqlite:///" + str(filepath))
        return cls(engine)

    def _require_table(self, data_or_dataclass):
        table_name = self._get_table_name(data_or_dataclass)
        table = self.metadata.tables.get(table_name)

        if table is None:
            table = self._create_table(table_name, data_or_dataclass)

        return table

    def get_table(self, data_or_dataclass):
        table_name = self._get_table_name(data_or_dataclass)
        table = self.metadata.tables.get(table_name)

        if table is None:
            raise ValueError('No table named: {}'.format(table_name))

        return table

    def _create_table(self, table_name, data_or_dataclass):
        # Add column for key fields of inputdata and all fields of outputdata.
        columns = [sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True)]

        for field in dataclasses.fields(data_or_dataclass):
            columns.append(self._create_column(field))

        # Create table.
        table = sqlalchemy.Table(table_name, self.metadata, *columns)
        self.metadata.create_all(self.engine, tables=[table])
        logger.debug('Create table "{}"'.format(table_name))

        return table

    def _create_column(self, field):
        if dataclasses.is_dataclass(field.type):
            subtable = self._require_table(field.type)
            return sqlalchemy.Column(field.name + '_id', None, sqlalchemy.ForeignKey(subtable.name + '.id'))

        if issubclass(field.type, enum.Enum):
            column_type = sqlalchemy.Enum(field.type)
        elif issubclass(field.type, str) and iskeyfield(field):
            column_type = sqlalchemy.String(collation="NOCASE")
        else:
            column_type = self.TYPE_TO_SQLTYPE.get(field.type)

        if column_type is None:
            raise ValueError("Cannot convert {} to SQL column".format(field.name))

        nullable = field.default is None

        return sqlalchemy.Column(field.name, column_type, nullable=nullable)

    def _get_rowid(self, data):
        """
        Returns the row of the dataclass if it exists.
        If not, ``None`` is returned
        Args:
            data (dataclasses.dataclass): instance
        Returns:
            int: row of the dataclass instance in its table, ``None`` if not found
        """
        if hasattr(data, '_rowid'):
            return data._rowid

        table_name = self._get_table_name(data)
        table = self.metadata.tables.get(table_name)
        if table is None:
            return None

        clauses = []
        for field in keyfields(data):
            value = getattr(data, field.name)

            if dataclasses.is_dataclass(field.type):
                row_id = self._get_rowid(value)
                clause = table.c[field.name + '_id'] == row_id

            else:
                clause = table.c[field.name] == value

            clauses.append(clause)

        if not clauses:
            logger.debug('No key fields')
            return None

        statement = sqlalchemy.sql.select([table.c.id]).where(sqlalchemy.sql.and_(*clauses))
        logger.debug("Find statement: {}", str(statement.compile()).replace("\n", ""))

        with self.engine.begin() as conn:
            rowid = conn.execute(statement).scalar()
            if not rowid:
                return None

            data._rowid = rowid
            return rowid

    def exists(self, data):
        return self._get_rowid(data) is not None

    def add(self, data, check_exists=True):
        # Check if exists
        if hasattr(data, '_rowid'):
            return data._rowid

        if check_exists:
            rowid = self._get_rowid(data)
            if rowid is not None:
                return rowid

        # Create row
        row = {}
        for field in dataclasses.fields(data):
            name = field.name
            value = getattr(data, name)

            if dataclasses.is_dataclass(value):
                row[name + '_id'] = self.add(value, check_exists)
            else:
                row[name] = value

        # Insert
        table = self._require_table(data)

        with self.engine.begin() as conn:
            result = conn.execute(table.insert(), row)  # pylint: disable=no-value-for-parameter
            logger.debug("Added output to table {}".format(table.name))
            rowid = result.inserted_primary_key[0]
            data._rowid = rowid
            return rowid

class MongoModel(_DatabaseModel):

    def __init__(self, database_name, *client_args, **client_kwargs):
        self.client = pymongo.MongoClient(*client_args, **client_kwargs)
        self.db = self.client[database_name]

    def _convert_value(self, field, value):
        if issubclass(field.type, enum.Enum):
            return value.name
        elif issubclass(field.type, datetime.date):
            return datetime.datetime(value.year, value.month, value.day)
        else:
            return value

    def _create_query(self, data, parents=()):
        query = {}
        for field in keyfields(data):
            value = getattr(data, field.name)

            if dataclasses.is_dataclass(field.type):
                query.update(self._create_query(value, parents + (field.name,)))
            else:
                query['.'.join(parents) + field.name] = self._convert_value(field, value)

        return query

    def _get_objectid(self, data):
        if hasattr(data, '_objectid'):
            return data._objectid

        table_name = self._get_table_name(data)
        if table_name not in self.db.list_collection_names():
            return None

        collection = self.db[table_name]
        query = self._create_query(data)

        if not query:
            logger.debug('No key fields')
            return None

        logger.debug("Find statement: {}", str(query).replace("\n", ""))

        result = collection.find_one(query)
        if result is None:
            return None

        objectid = result['_id']
        data._objectid = objectid
        return objectid

    def exists(self, data):
        return self._get_objectid(data) is not None

    def _create_row(self, data):
        row = {}

        for field in dataclasses.fields(data):
            name = field.name
            value = getattr(data, name)

            if dataclasses.is_dataclass(value):
                row[name] = self._create_row(value)
            else:
                row[name] = self._convert_value(field, value)

        return row

    def add(self, data, check_exists=True):
        # Check if exists
        if hasattr(data, '_objectid'):
            return data._objectid

        if check_exists:
            objectid = self._get_objectid(data)
            if objectid is not None:
                return objectid

        # Insert
        table_name = self._get_table_name(data)
        row = self._create_row(data)

        objectid = self.db[table_name].insert_one(row).inserted_id
        logger.debug("Added output to table {}".format(table_name))

        data._objectid = objectid
        return objectid
