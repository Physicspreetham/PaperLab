import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crop_budget import CropBudget, CropBudgetExceeded


def test_ninth_crop_stops_without_accepting_or_resetting_page():
    budget = CropBudget(8)
    args = {"paper_id": 1, "question_number": "55", "output_filename": "sfig1.png"}
    for _ in range(8):
        budget.check(args)
    with pytest.raises(CropBudgetExceeded, match="review required"):
        budget.check({**args, "page_number": 99})
    budget.check({**args, "output_filename": "sfig2.png"})
    budget.check({**args, "question_number": "67"})


@pytest.mark.parametrize("limit", [0, -1, 3, True, 8.5, "8"])
def test_invalid_limits_are_rejected(limit):
    with pytest.raises(ValueError):
        CropBudget(limit)
