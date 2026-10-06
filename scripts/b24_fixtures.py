"""Reuse real domain setup fixtures, without collecting their tests a second time."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests/foundation"))
from test_consignments import consignment  # noqa: E402,F401
from test_count_period import counting  # noqa: E402,F401
from test_issues import issuing  # noqa: E402,F401
from test_move_quality import movement  # noqa: E402,F401
from test_openings import opening  # noqa: E402,F401
from test_orders import orders  # noqa: E402,F401
from test_receipts import receiving  # noqa: E402,F401
from test_reports_exports import reports  # noqa: E402,F401
from test_returns import returning  # noqa: E402,F401
from test_reversals import reversal  # noqa: E402,F401
from test_transfers import transfer  # noqa: E402,F401
