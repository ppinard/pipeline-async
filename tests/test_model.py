""""""

# Standard library modules.
import datetime
import enum

# Third party modules.
import pytest
import attr

# Local modules.
from pipeline_async.model import SqlModel
import mock

# Globals and constants variables.


class Fruit(enum.Enum):
    APPLE = "apple"
    ORANGE = "orange"


@attr.s
class SubData:
    integer: int = attr.ib(metadata={'key': True})


@attr.s
class Data:
    integer: int = attr.ib(metadata={'key': True})
    number: float = attr.ib()
    text: str = attr.ib()
    binary: bytes = attr.ib()
    event: datetime.datetime = attr.ib()
    event_date: datetime.date = attr.ib()
    question: bool = attr.ib()
    fruit: Fruit = attr.ib()
    subdata: SubData = attr.ib(metadata={'key': True})


list_data = [
    mock.ArithmeticData(3, 4, 7),
    Data(
        1,
        3.0,
        "abc",
        b"def",
        datetime.datetime(2019, 6, 16, 12, 34, 56),
        datetime.date(2019, 6, 16),
        True,
        Fruit.APPLE,
        SubData(5),
    ),
]


@pytest.mark.parametrize("data", list_data)
def test_sqlmodel_exists_not(sqlmodel, data):
    assert not sqlmodel.exists(data)


@pytest.mark.parametrize("data", list_data)
def test_sqlmodel_exists(sqlmodel, data):
    rowid = sqlmodel.add(data)
    assert rowid == 1
    assert sqlmodel.exists(data)


def test_sqlmodel_exists_nodata(sqlmodel):
    data = mock.ArithmeticData(3, 4, 7)
    sqlmodel.add(data)

    data = mock.ArithmeticData(3, 4, -1)
    assert sqlmodel.exists(data)

    data = mock.ArithmeticData(3, 99, 102)
    assert not sqlmodel.exists(data)

