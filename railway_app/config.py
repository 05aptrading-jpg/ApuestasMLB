# Re-export parent config — avoids stale copy issues
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *  # noqa
