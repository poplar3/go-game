import sys, json
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from gogame.problems.sgf_import import file_to_problems
print(json.dumps([file_to_problems(Path(f), 1000, 1, "imp") for f in sys.argv[2:]], ensure_ascii=False, sort_keys=True))
