from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

spec = spec_from_file_location("remediate", Path(__file__).parent / "lambda" / "remediate.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)
process_event = module.process_event
