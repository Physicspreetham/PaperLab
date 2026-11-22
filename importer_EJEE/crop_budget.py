"""Bound crop-tool retries without silently accepting an imperfect figure."""
from collections import Counter


class CropBudgetExceeded(RuntimeError):
    pass


class CropBudget:
    def __init__(self, maximum=8):
        if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 4:
            raise ValueError("max_crop_calls_per_figure must be an integer >= 4")
        self.maximum = maximum
        self.used = Counter()

    def check(self, args):
        # Filename identity cannot reset the budget by changing page/tool.
        key = (args.get("paper_id"), str(args.get("question_number")),
               args.get("output_filename"))
        if self.used[key] >= self.maximum:
            raise CropBudgetExceeded(
                f"Crop review required for {key[1]}/{key[2]}: "
                f"{self.maximum} crop calls already used. No further paid "
                "refinement is permitted for this figure. Inspect the original "
                "body for damaged labels/adjacent text and supply a reviewed "
                "crop or repaired source; do not mark it complete."
            )
        self.used[key] += 1
