import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from tests import test_online_parsers as t1
from tests import run_tests as t2

print('Running parser unit tests...')
t1.test_psxdatacenter_parser(); print(' psxdatacenter: OK')
t1.test_gamehacking_json_parser(); print(' gamehacking json: OK')
t1.test_normalize_code_lines_edge(); print(' normalize edge: OK')
print('Running basic parsing tests...')
t2.run()
print('All tests OK')
