""""""

# Standard library modules.

# Third party modules.
import pytest

# Local modules.
from pipeline_async.pipeline import Pipeline
import mock

# Globals and constants variables.

@pytest.mark.parametrize('pipeline,expected_values', [
    (Pipeline([mock.ArithmeticTask('arithmetic')]), [7, -1]),
    (Pipeline([mock.ArithmeticTask('arithmetic'), mock.ArithmeticOutputToPowerInputTask('convert'), mock.PowerTask('power')]), [49, 343, 1, -1])
])
@pytest.mark.asyncio
async def test_pipeline_run(pipeline, expected_values):
    inputdata = mock.ArithmeticInput(3, 4)
    list_outputdata = await pipeline.run(inputdata)

    assert len(list_outputdata) == len(expected_values)

    for outputdata, expected_value in zip(list_outputdata, expected_values):
        assert outputdata.value == expected_value

@pytest.mark.parametrize('pipeline', [
    Pipeline([mock.FailedTask('failed')]),
    Pipeline([mock.ArithmeticTask('arithmetic'), mock.FailedTask('failed')]),
])
@pytest.mark.asyncio
async def test_pipeline_run_failed(pipeline):
    with pytest.raises(RuntimeError):
        inputdata = mock.ArithmeticInput(3, 4)
        await pipeline.run(inputdata)